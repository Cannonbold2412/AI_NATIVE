"use strict";
/**
 * Build Studio Electron main process.
 *
 * Spawns the PyInstaller backend (or `python backend.py` in dev) and bridges
 * `ipcMain.handle('python:cmd', ...)` to its stdin/stdout JSON-RPC. Streaming
 * `{type:"event"}` lines are forwarded to the focused renderer. The backend is
 * restarted up to 3 times on unexpected exit before surfacing a fatal dialog.
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const readline = require("readline");
const { Bridge } = require("./bridge");

const IS_DEV = !app.isPackaged;
const MAX_BACKEND_RESTARTS = 3;
const APP_ICON_PATH = path.join(__dirname, "build", "icon.png");

let mainWindow = null;
let backend = null;
let backendRestarts = 0;
let bridge = null;

// ─── Backend lifecycle ────────────────────────────────────────────────────────

function backendCommand() {
  if (IS_DEV) {
    const py = process.env.CONXA_PYTHON || "python3";
    const script = path.join(__dirname, "..", "python", "backend.py");
    return { cmd: py, args: [script] };
  }
  // Packaged: PyInstaller --onedir backend placed via electron-builder extraFiles.
  const exe = process.platform === "win32" ? "backend.exe" : "backend";
  return { cmd: path.join(process.resourcesPath, "backend", exe), args: [] };
}

function startBackend() {
  const { cmd, args } = backendCommand();
  backend = spawn(cmd, args, {
    stdio: ["pipe", "pipe", "pipe"], // all pipes; windowsHide suppresses the console window
    windowsHide: true,
    env: { ...process.env },
  });

  bridge = new Bridge(
    (line) => backend.stdin.write(line),
    (event) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("python:event", event);
      }
    }
  );

  const rl = readline.createInterface({ input: backend.stdout });
  rl.on("line", (line) => bridge.handleLine(line));

  backend.on("exit", (code) => {
    if (bridge) bridge.rejectAll(`backend exited (code ${code})`);

    if (backendRestarts < MAX_BACKEND_RESTARTS && !app.isQuitting) {
      backendRestarts += 1;
      startBackend();
    } else if (!app.isQuitting) {
      dialog.showErrorBox(
        "Conxa Build Studio",
        "The backend stopped unexpectedly and could not be restarted. " +
          "Please restart the app. Logs are in the app data directory."
      );
    }
  });
}

function callBackend(type, payload) {
  if (!backend || backend.killed || !bridge) {
    return Promise.reject(new Error("backend_not_running"));
  }
  return bridge.call(type, payload);
}

// ─── IPC surface for the renderer ──────────────────────────────────────────────

ipcMain.handle("python:cmd", async (_e, { type, payload }) => {
  try {
    const result = await callBackend(type, payload);
    return { ok: true, result };
  } catch (err) {
    return { ok: false, code: err.code || "error", message: err.message, trace: err.trace };
  }
});

ipcMain.handle("open-external", (_e, url) => shell.openExternal(url));

// ─── Window ─────────────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#1a1a1a",
    icon: APP_ICON_PATH,
    titleBarStyle: "hiddenInset",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (IS_DEV && process.env.CONXA_RENDERER_URL) {
    mainWindow.loadURL(process.env.CONXA_RENDERER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "renderer", "dist", "index.html"));
  }
}

// ─── Auto-update (electron-updater) ─────────────────────────────────────────────

function initAutoUpdate() {
  if (IS_DEV) return;
  let autoUpdater;
  try {
    ({ autoUpdater } = require("electron-updater"));
  } catch {
    return; // dependency not bundled in this build
  }
  autoUpdater.channel = process.env.CONXA_UPDATE_CHANNEL || "stable";
  autoUpdater.on("update-downloaded", () => {
    dialog
      .showMessageBox({
        type: "info",
        buttons: ["Restart now", "Later"],
        message: "A new version of Build Studio is ready. Restart to apply.",
      })
      .then((res) => {
        if (res.response === 0) autoUpdater.quitAndInstall();
      });
  });
  autoUpdater.checkForUpdatesAndNotify();
  setInterval(() => autoUpdater.checkForUpdatesAndNotify(), 4 * 60 * 60 * 1000);
}

// ─── App lifecycle ──────────────────────────────────────────────────────────

app.whenReady().then(() => {
  if (process.platform === "win32") {
    app.setAppUserModelId("ai.conxa.build-studio");
  }
  // Custom scheme for the OAuth callback (registered at install on Windows).
  if (!app.isDefaultProtocolClient("conxa-studio")) {
    app.setAsDefaultProtocolClient("conxa-studio");
  }
  startBackend();
  createWindow();
  initAutoUpdate();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  app.isQuitting = true;
  if (backend && !backend.killed) backend.kill();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

module.exports = { callBackend };
