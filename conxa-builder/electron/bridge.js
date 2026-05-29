"use strict";
/**
 * Pure JSON-RPC correlation for the Python backend bridge.
 *
 * Electron-free so it can be unit-tested with plain node. `main.js` wires a
 * Bridge to the spawned process: stdout lines go to `handleLine`, results
 * resolve the matching `call`, and `{type:"event"}` lines fan out to onEvent.
 */

const crypto = require("crypto");

class Bridge {
  /**
   * @param {(line: string) => void} write  writes a line to backend stdin
   * @param {(event: object) => void} onEvent  receives streaming events
   * @param {() => string} [idFactory]  override id generation (tests)
   */
  constructor(write, onEvent, idFactory) {
    this._write = write;
    this._onEvent = onEvent || (() => {});
    this._idFactory = idFactory || (() => crypto.randomUUID());
    this._pending = new Map();
  }

  call(type, payload) {
    return new Promise((resolve, reject) => {
      const id = this._idFactory();
      this._pending.set(id, { resolve, reject });
      this._write(JSON.stringify({ id, type, payload: payload || {} }) + "\n");
    });
  }

  handleLine(line) {
    const trimmed = String(line || "").trim();
    if (!trimmed) return;
    let msg;
    try {
      msg = JSON.parse(trimmed);
    } catch {
      return;
    }
    if (msg.type === "event") {
      this._onEvent(msg);
      return;
    }
    const entry = this._pending.get(msg.id);
    if (!entry) return;
    this._pending.delete(msg.id);
    if (msg.type === "result") {
      entry.resolve(msg.result);
    } else {
      const err = new Error(msg.message || "backend_error");
      err.code = msg.code;
      err.trace = msg.trace;
      entry.reject(err);
    }
  }

  /** Reject all in-flight calls (used when the backend exits). */
  rejectAll(reason) {
    for (const { reject } of this._pending.values()) reject(new Error(reason));
    this._pending.clear();
  }

  get pendingCount() {
    return this._pending.size;
  }
}

module.exports = { Bridge };
