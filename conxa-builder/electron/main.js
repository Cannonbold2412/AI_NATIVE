"use strict";
/**
 * Build Studio Electron main process.
 *
 * Spawns the PyInstaller backend (or `python backend.py` in dev) and bridges
 * `ipcMain.handle('python:cmd', ...)` to its stdin/stdout JSON-RPC. Streaming
 * `{type:"event"}` lines are forwarded to the focused renderer. The backend is
 * restarted up to 3 times on unexpected exit before surfacing a fatal dialog.
 */

const { app, BrowserWindow, ipcMain, dialog, shell, Menu } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const readline = require("readline");
const { Bridge } = require("./bridge");

const IS_DEV = !app.isPackaged;
const MAX_BACKEND_RESTARTS = 3;

// Preload runs in a separate context where process.defaultApp is not reliable
// for our node-launched dev wrapper. Pass the main-process packaging state
// explicitly so the renderer can skip packaged-only bootstrap in dev.
process.env.CONXA_ELECTRON_IS_PACKAGED = app.isPackaged ? "1" : "0";

// Enforce single instance so second-instance fires (required for Windows deep-link handling).
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

// Windows: app already running — focus it and forward the deep-link URL.
app.on("second-instance", (_event, argv) => {
  const url = argv.find((a) => a.startsWith("conxa-studio://"));
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
    if (url) mainWindow.webContents.send("deep-link", url);
  }
});

// macOS: OS fires this when the app is already running and a conxa-studio:// link is opened.
app.on("open-url", (event, url) => {
  event.preventDefault();
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("deep-link", url);
  }
});
const APP_ICON_PATH = path.join(__dirname, "build", "icon.png");

let mainWindow = null;
let backend = null;
let backendRestarts = 0;
let bridge = null;
// Minimal semver greater-than without an extra dependency.
function semverGt(a, b) {
  const pa = a.replace(/^v/, "").split(".").map(Number);
  const pb = b.replace(/^v/, "").split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) > (pb[i] || 0)) return true;
    if ((pa[i] || 0) < (pb[i] || 0)) return false;
  }
  return false;
}

// Strip "studio-v" or "v" prefix from manifest version strings → bare semver.
function stripVersion(v) {
  return v.replace(/^studio-v/i, "").replace(/^v/, "");
}

// Stashed between update:check and update:start.
let pendingUpdate = null; // { winUrl, win256 }
let downloadedInstallerPath = null;

// ─── Backend lifecycle ────────────────────────────────────────────────────────

function backendCommand() {
  if (IS_DEV) {
    const defaultPy = process.platform === "win32" ? "python" : "python3";
    const venvPy = process.env.VIRTUAL_ENV
      ? path.join(process.env.VIRTUAL_ENV, process.platform === "win32" ? "Scripts\\python.exe" : "bin/python")
      : defaultPy;
    const py = process.env.CONXA_PYTHON || venvPy;
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
    env: {
      ...process.env,
      SKILL_ALLOW_NO_PROVIDERS: "1",
      // Production auth + cloud config baked in as defaults.
      // Set these env vars in the shell to override for dev/staging.
      CONXA_CLERK_DOMAIN:
        process.env.CONXA_CLERK_DOMAIN || "https://clerk.conxa.in",
      CONXA_CLERK_CLIENT_ID:
        process.env.CONXA_CLERK_CLIENT_ID || "Z7O8UdIVowd3Aegx",
      // CONXA_CLERK_CLIENT_SECRET is optional: auth_service uses PKCE (public client)
      // so the secret is not required for the token exchange. If Clerk is configured
      // as a confidential client, set this env var in the shell before `npm run dev`,
      // or set it as a GitHub Actions secret and pass it to the build step.
      // Never commit a default value here.
      ...(process.env.CONXA_CLERK_CLIENT_SECRET
        ? { CONXA_CLERK_CLIENT_SECRET: process.env.CONXA_CLERK_CLIENT_SECRET }
        : {}),
      CONXA_CLOUD_API:
        process.env.CONXA_CLOUD_API || "https://apis.conxa.in",
      // In dev, add source paths so Python can import conxa_core and conxa_compile
      // without requiring a full pip install. In packaged mode these directories
      // don't exist on disk and the frozen bundle has everything it needs — omit them.
      PYTHONPATH: (IS_DEV ? [
        path.join(__dirname, "..", "..", "packages", "conxa-core"),
        path.join(__dirname, "..", "python"),
        process.env.PYTHONPATH || "",
      ] : [process.env.PYTHONPATH || ""]).filter(Boolean).join(path.delimiter),
    },
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

  const rlErr = readline.createInterface({ input: backend.stderr });
  rlErr.on("line", (line) => console.error("[backend]", line));

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

ipcMain.handle("dialog:pick-file", async (_e, filters) => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: filters ?? [{ name: "Images", extensions: ["png", "jpg", "jpeg", "ico"] }],
  });
  return canceled ? null : (filePaths[0] ?? null);
});

function windowFromEvent(event) {
  return BrowserWindow.fromWebContents(event.sender);
}

ipcMain.handle("window:minimize", (event) => {
  windowFromEvent(event)?.minimize();
});

ipcMain.handle("window:toggle-maximize", (event) => {
  const win = windowFromEvent(event);
  if (!win) return false;
  if (win.isMaximized()) {
    win.unmaximize();
  } else {
    win.maximize();
  }
  return win.isMaximized();
});

ipcMain.handle("window:close", (event) => {
  windowFromEvent(event)?.close();
});

ipcMain.handle("window:is-maximized", (event) => Boolean(windowFromEvent(event)?.isMaximized()));

ipcMain.handle("app:version", () => app.getVersion());

// Checks for a newer version by fetching the Cloud studio-manifest.
// Fail-open: any error returns { available: false, error } so startup is never bricked.
// In dev, skip entirely unless CONXA_FORCE_UPDATE_SCREEN=1 (avoids blocking the dev loop).
ipcMain.handle("update:check", async () => {
  const currentVersion = app.getVersion();
  if (process.env.CONXA_FORCE_UPDATE_SCREEN === "1") {
    return { available: true, currentVersion, latestVersion: "99.0.0" };
  }
  if (IS_DEV) {
    return { available: false, currentVersion };
  }
  const CLOUD_API = process.env.CONXA_CLOUD_API || "https://apis.conxa.in";
  try {
    const res = await fetch(`${CLOUD_API}/api/v1/updates/studio-manifest`, {
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) {
      const error = `Manifest fetch failed: HTTP ${res.status}`;
      return { available: false, currentVersion, error };
    }
    const manifest = await res.json();
    const latestVersion = stripVersion(manifest.version || "");
    if (!latestVersion) {
      return { available: false, currentVersion, error: "Manifest returned no version" };
    }
    const available = semverGt(latestVersion, currentVersion);
    if (available) {
      pendingUpdate = { winUrl: manifest.win_url || "", winSha256: manifest.win_sha256 || "" };
    }
    return { available, currentVersion, latestVersion };
  } catch (err) {
    return { available: false, currentVersion, error: err.message };
  }
});

// Downloads the installer from pendingUpdate.winUrl with live progress events,
// then stores the path for update:install.
ipcMain.handle("update:start", async () => {
  if (!pendingUpdate?.winUrl) {
    sendUpdateStatus({ phase: "error", message: "No update URL available — run check first" });
    return;
  }
  const https = require("https");
  const fss = require("fs");
  const crypto = require("crypto");
  const destPath = path.join(app.getPath("temp"), "conxa-studio-update.exe");

  function sendUpdateStatus(payload) {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("update:status", payload);
    }
  }

  // Follow redirects (GitHub release asset URLs 302 → signed CDN URL).
  function download(url, dest, resolve, reject, hops = 0) {
    if (hops > 5) { reject(new Error("Too many redirects")); return; }
    https.get(url, (response) => {
      if (response.statusCode === 301 || response.statusCode === 302 || response.statusCode === 307 || response.statusCode === 308) {
        const location = response.headers.location;
        response.resume();
        if (!location) { reject(new Error("Redirect with no Location header")); return; }
        download(location, dest, resolve, reject, hops + 1);
        return;
      }
      if (response.statusCode !== 200) {
        reject(new Error(`Download failed: HTTP ${response.statusCode}`));
        return;
      }
      const total = parseInt(response.headers["content-length"] || "0", 10);
      let transferred = 0;
      let lastEmit = 0;
      const hash = crypto.createHash("sha256");
      const file = fss.createWriteStream(dest);

      response.on("data", (chunk) => {
        transferred += chunk.length;
        hash.update(chunk);
        const now = Date.now();
        if (now - lastEmit > 250) {
          lastEmit = now;
          const elapsed = (now - startTime) / 1000 || 1;
          sendUpdateStatus({
            phase: "download-progress",
            percent: total ? (transferred / total) * 100 : 0,
            bytesPerSecond: Math.round(transferred / elapsed),
            transferred,
            total,
          });
        }
      });
      response.pipe(file);
      const startTime = Date.now();
      file.on("finish", () => resolve({ digest: hash.digest("hex") }));
      file.on("error", reject);
      response.on("error", reject);
    }).on("error", reject);
  }

  try {
    const { digest } = await new Promise((resolve, reject) =>
      download(pendingUpdate.winUrl, destPath, resolve, reject)
    );

    if (pendingUpdate.winSha256) {
      if (digest.toLowerCase() !== pendingUpdate.winSha256.toLowerCase()) {
        fss.unlink(destPath, () => {});
        sendUpdateStatus({ phase: "error", message: "Checksum mismatch — download may be corrupt" });
        return;
      }
    }

    downloadedInstallerPath = destPath;
    sendUpdateStatus({ phase: "downloaded" });
  } catch (err) {
    sendUpdateStatus({ phase: "error", message: err.message });
  }
});

// Launches the downloaded NSIS installer silently then quits.
// Args match electron-updater's NsisUpdater.doInstall exactly:
//   --updated  → tells NSIS script this is an update (not a fresh install)
//   /S         → silent mode (no wizard UI)
//   --force-run → relaunch the app after installation
ipcMain.handle("update:install", () => {
  if (!downloadedInstallerPath) return;
  const { spawn: nodeSpawn } = require("child_process");
  nodeSpawn(downloadedInstallerPath, ["--updated", "/S", "--force-run"], {
    detached: true,
    stdio: "ignore",
  }).unref();
  app.quit();
});

// ─── Window ─────────────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#1a1a1a",
    icon: APP_ICON_PATH,
    title: "Conxa Build Studio",
    frame: false,
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

  // The application menu is suppressed (Menu.setApplicationMenu(null)), which also
  // strips the default F12 / Ctrl+Shift+I DevTools accelerators. Re-register them in dev.
  if (IS_DEV) {
    mainWindow.webContents.on("before-input-event", (_event, input) => {
      const isToggle =
        input.key === "F12" ||
        (input.control && input.shift && input.key.toLowerCase() === "i");
      if (isToggle) mainWindow.webContents.toggleDevTools();
    });
  }

  const sendMaximizeState = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    mainWindow.webContents.send("window:maximized", mainWindow.isMaximized());
  };
  mainWindow.on("maximize", sendMaximizeState);
  mainWindow.on("unmaximize", sendMaximizeState);
}

// ─── App lifecycle ──────────────────────────────────────────────────────────

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);

  if (process.platform === "win32") {
    app.setAppUserModelId("ai.conxa.build-studio");
  }
  // Custom scheme for the OAuth callback (registered at install on Windows).
  if (!app.isDefaultProtocolClient("conxa-studio")) {
    app.setAsDefaultProtocolClient("conxa-studio");
  }
  startBackend();
  createWindow();

  // Windows cold-launch: deep link URL is passed as a CLI arg when the app starts fresh.
  const coldUrl = process.argv.find((a) => a.startsWith("conxa-studio://"));
  if (coldUrl) {
    mainWindow.webContents.once("did-finish-load", () => {
      mainWindow.webContents.send("deep-link", coldUrl);
    });
  }

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
