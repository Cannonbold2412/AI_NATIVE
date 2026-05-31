"use strict";

const { spawn } = require("child_process");
const path = require("path");

const root = path.join(__dirname, "..");
const env = {
  ...process.env,
  CONXA_RENDERER_URL: process.env.CONXA_RENDERER_URL || "http://localhost:5174",
};

delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(process.execPath, [require.resolve("electron/cli"), "."], {
  cwd: root,
  env,
  stdio: "inherit",
  windowsHide: false,
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    child.kill(signal);
  });
}

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
