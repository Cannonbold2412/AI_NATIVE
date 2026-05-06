const TRACKER_URL = process.env.CONXA_TRACKER_URL || "";

// Fire-and-forget: never awaited, never throws.
function send(event) {
  if (!TRACKER_URL) return;
  try {
    fetch(TRACKER_URL, { method: "POST", body: String(event) }).catch(() => {});
  } catch (_) {}
}

module.exports = { send };
