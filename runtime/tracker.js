"use strict";

const https = require("https");
const http  = require("http");
const url   = require("url");

const MAX_QUEUE   = 50;
const FLUSH_EVERY = 10;   // events before auto-flush
const FLUSH_MS    = 2000; // timer interval

/**
 * Map a runtime error to a compact failure reason code.
 * Exported so server.js can reuse it for wf_fail.
 */
function mapErrorToCode(err) {
  const msg = (err && err.message) ? err.message : String(err || "");
  if (/url .* does not match/i.test(msg))    return "url_mismatch";
  if (/timeout/i.test(msg))                  return "timeout";
  if (/net::|ERR_|navigation/i.test(msg))    return "navigation_failed";
  if (/cancel/i.test(msg))                   return "cancelled";
  return "selector_missing";
}

/**
 * createTracker(trackingConfig, runtimeContext) → tracker
 *
 * trackingConfig: { enabled, tracking_url, tracking_token,
 *                   company_id, schema_version, protocol_version }
 * runtimeContext: { runtime_version, plugin_id, plugin_version, company_id }
 */
function createTracker(trackingConfig, runtimeContext) {
  const cfg = trackingConfig  || {};
  const ctx = runtimeContext  || {};
  const log = typeof ctx.log === "function" ? ctx.log : null;

  function _warn(msg, extra) {
    if (!log) return;
    try { log("warn", msg, extra || {}); } catch (_) {}
  }

  // Disabled: return a no-op tracker so callers never branch
  if (!cfg.enabled) {
    const noop = () => {};
    return {
      forRun:  () => ({ emit: noop }),
      flush:   () => Promise.resolve(),
      destroy: noop,
    };
  }

  let queue    = [];
  let _flushing = false;
  let _timer   = setInterval(_tick, FLUSH_MS);
  if (_timer.unref) _timer.unref(); // don't prevent process exit

  // Active run context (set by forRun)
  let _runCtx = { rid: "", uid: "", wid: "" };

  function _tick() {
    if (!_flushing && queue.length > 0) _flushNow();
  }

  async function _flushNow() {
    if (_flushing || queue.length === 0) return;
    _flushing = true;
    const batch = queue.splice(0, queue.length);
    try {
      await _post(batch);
    } catch (_) {
      // silent — telemetry must never surface errors
    } finally {
      _flushing = false;
    }
  }

  function _post(events) {
    return new Promise((resolve) => {
      const payload = JSON.stringify({
        v:   cfg.protocol_version || 1,
        sv:  cfg.schema_version   || 1,
        cid: cfg.company_id       || ctx.company_id || "",
        pid: ctx.plugin_id        || "",
        pv:  ctx.plugin_version   || "",
        rv:  ctx.runtime_version  || "",
        rid: _runCtx.rid,
        uid: _runCtx.uid,
        wid: _runCtx.wid,
        evts: events,
      });

      let trackingUrl;
      try {
        trackingUrl = new url.URL(cfg.tracking_url);
      } catch (_) {
        _warn("tracking_invalid_url", { url: cfg.tracking_url || "" });
        return resolve();
      }

      const lib     = trackingUrl.protocol === "https:" ? https : http;
      const options = {
        hostname: trackingUrl.hostname,
        port:     trackingUrl.port || (trackingUrl.protocol === "https:" ? 443 : 80),
        path:     trackingUrl.pathname + (trackingUrl.search || ""),
        method:   "POST",
        headers: {
          "Content-Type":      "application/json",
          "Content-Length":    Buffer.byteLength(payload),
          "X-Tracking-Token":  cfg.tracking_token  || "",
          "X-Runtime-Version": ctx.runtime_version || "",
        },
      };

      try {
        const req = lib.request(options, (res) => {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            _warn("tracking_http_status", { status: res.statusCode, host: trackingUrl.hostname, path: trackingUrl.pathname });
          }
          res.resume();
          resolve();
        });
        req.on("error", (err) => {
          _warn("tracking_request_failed", { host: trackingUrl.hostname, error: err && err.message ? err.message : String(err) });
          resolve();
        });
        req.setTimeout(5000, () => {
          _warn("tracking_request_timeout", { host: trackingUrl.hostname, path: trackingUrl.pathname });
          req.destroy();
          resolve();
        });
        req.write(payload);
        req.end();
      } catch (_) {
        _warn("tracking_request_failed", { host: trackingUrl.hostname, error: "request_setup_failed" });
        resolve();
      }
    });
  }

  function _enqueue(event) {
    if (queue.length >= MAX_QUEUE) queue.shift(); // drop oldest
    queue.push(event);
    if (queue.length >= FLUSH_EVERY) _flushNow();
  }

  /**
   * Bind a run_id and optional user context.
   * Returns a scoped { emit } tied to this run.
   */
  function forRun(runId, userCtx) {
    _runCtx = {
      rid: runId || "",
      uid: (userCtx && userCtx.uid) || "",
      wid: (userCtx && userCtx.wid) || "",
    };
    return {
      emit(eventCode, fields) {
        const evt = Object.assign({ e: eventCode, ts: Date.now() }, fields || {});
        _enqueue(evt);
      },
    };
  }

  async function flush() {
    await _flushNow();
  }

  function destroy() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  return { forRun, flush, destroy };
}

module.exports = { createTracker, mapErrorToCode };
