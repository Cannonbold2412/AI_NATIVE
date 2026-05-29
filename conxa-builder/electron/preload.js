"use strict";
/**
 * Preload bridge. Exposes a minimal, typed surface to the renderer over the
 * context-isolated boundary — no direct Node or ipcRenderer access leaks.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("conxa", {
  /** Invoke a backend command. Resolves to { ok, result } | { ok:false, code, message }. */
  cmd: (type, payload) => ipcRenderer.invoke("python:cmd", { type, payload }),

  /** Subscribe to streaming backend events. Returns an unsubscribe fn. */
  onEvent: (handler) => {
    const listener = (_e, msg) => handler(msg);
    ipcRenderer.on("python:event", listener);
    return () => ipcRenderer.removeListener("python:event", listener);
  },

  openExternal: (url) => ipcRenderer.invoke("open-external", url),
});
