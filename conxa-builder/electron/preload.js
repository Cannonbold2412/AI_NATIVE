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

  windowControls: {
    minimize: () => ipcRenderer.invoke("window:minimize"),
    toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
    close: () => ipcRenderer.invoke("window:close"),
    isMaximized: () => ipcRenderer.invoke("window:is-maximized"),
    onMaximizeChange: (handler) => {
      const listener = (_e, isMaximized) => handler(isMaximized);
      ipcRenderer.on("window:maximized", listener);
      return () => ipcRenderer.removeListener("window:maximized", listener);
    },
  },

  /** Subscribe to deep-link URLs sent from the main process. Returns an unsubscribe fn. */
  onDeepLink: (handler) => {
    const listener = (_e, url) => handler(url);
    ipcRenderer.on("deep-link", listener);
    return () => ipcRenderer.removeListener("deep-link", listener);
  },
});
