/**
 * In-page capture bridge: runs inside the browser context.
 * Serializes the active element / event target and calls the Playwright binding
 * `__skillReport` with a JSON-serializable payload.
 */
(() => {
  if (window.__SKILL_BRIDGE_V1__) return;
  window.__SKILL_BRIDGE_V1__ = true;

  const CAP =
    typeof window !== "undefined" && window.__SKILL_CAPTURE_PROFILE__
      ? window.__SKILL_CAPTURE_PROFILE__
      : {};
  const cssDepthMax = Number(CAP.css_path_max_depth) > 0 ? Number(CAP.css_path_max_depth) : 8;
  const xpathDepthMax = Number(CAP.xpath_max_depth) > 0 ? Number(CAP.xpath_max_depth) : 10;
  const anchorCandMax = Number(CAP.anchor_candidates_max) > 0 ? Number(CAP.anchor_candidates_max) : 40;
  const classSliceMax = Number(CAP.class_slice_max) >= 0 ? Number(CAP.class_slice_max) : 2;
  const safeTextMaxEl = Number(CAP.safe_text_max) > 0 ? Number(CAP.safe_text_max) : 120;
  const pageFpMax = Number(CAP.page_fingerprint_slice) > 0 ? Number(CAP.page_fingerprint_slice) : 4000;
  const siblingsMax = Number(CAP.siblings_summarize_max) > 0 ? Number(CAP.siblings_summarize_max) : 6;
  const inputDebounceMs = Number(CAP.input_debounce_ms) > 0 ? Number(CAP.input_debounce_ms) : 350;
  const scrollDebounceMs = Number(CAP.scroll_debounce_ms) > 0 ? Number(CAP.scroll_debounce_ms) : 220;

  function djb2(str) {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
      hash = (hash * 33) ^ str.charCodeAt(i);
    }
    return (hash >>> 0).toString(16);
  }

  function pageFingerprint() {
    const href = location.href;
    const title = document.title || "";
    const text = (document.documentElement && document.documentElement.innerText) || "";
    const norm = text.replace(/\s+/g, " ").trim().slice(0, pageFpMax);
    return `${href}|${title}|${djb2(norm)}`;
  }

  function safeText(el, maxLen) {
    if (!el || !el.innerText) return "";
    return String(el.innerText).replace(/\s+/g, " ").trim().slice(0, maxLen);
  }

  function cssEscapeIdent(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
  }

  function isInteractiveNode(n) {
    if (!n || n.nodeType !== 1) return false;
    const tag = n.tagName.toLowerCase();
    if (tag === "button" || tag === "a" || tag === "input" || tag === "textarea" || tag === "select") {
      return true;
    }
    const r = ((n.getAttribute && n.getAttribute("role")) || "").toLowerCase();
    if (
      ["button", "link", "textbox", "checkbox", "radio", "switch", "tab", "menuitem", "option", "combobox"].indexOf(
        r
      ) >= 0
    ) {
      return true;
    }
    if (tag === "label" && n.htmlFor) return true;
    if (n.getAttribute && n.getAttribute("contenteditable") === "true") return true;
    if ((tag === "div" || tag === "span") && n.getAttribute && n.getAttribute("data-action")) return true;
    return false;
  }

  /** Resolve clicks on svg/path/shallow divs to the control the user meant (button, link, input, …). */
  function resolveMeaningfulTarget(el) {
    if (!el || el.nodeType !== 1) return null;
    let cur = el;
    for (let depth = 0; depth < 14 && cur; depth++) {
      if (isInteractiveNode(cur)) return cur;
      const tag = cur.tagName ? cur.tagName.toLowerCase() : "";
      if (tag === "body" || tag === "html") break;
      cur = cur.parentElement;
    }
    return null;
  }

  function buildCssPath(el) {
    if (!el || el.nodeType !== 1) return "";
    const parts = [];
    let cur = el;
    let depth = 0;
    while (cur && cur.nodeType === 1 && depth < cssDepthMax) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) {
        part = "#" + cssEscapeIdent(cur.id);
        parts.unshift(part);
        break;
      }
      if (cur.classList && cur.classList.length) {
        const cls = Array.from(cur.classList)
          .slice(0, classSliceMax)
          .map((c) => "." + cssEscapeIdent(c))
          .join("");
        part += cls;
      }
      const parent = cur.parentElement;
      if (parent) {
        const sameTagSiblings = Array.from(parent.children).filter(
          (n) => n.tagName === cur.tagName
        );
        if (sameTagSiblings.length > 1) {
          const idx = sameTagSiblings.indexOf(cur) + 1;
          part += `:nth-of-type(${idx})`;
        }
      }
      parts.unshift(part);
      cur = parent;
      depth++;
    }
    return parts.join(" > ");
  }

  function buildXPath(el) {
    if (!el || el.nodeType !== 1) return "";
    const segs = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < xpathDepthMax) {
      let ix = 1;
      let sib = node.previousElementSibling;
      while (sib) {
        if (sib.tagName === node.tagName) ix++;
        sib = sib.previousElementSibling;
      }
      segs.unshift(`${node.tagName.toLowerCase()}[${ix}]`);
      node = node.parentElement;
      depth++;
    }
    return "/" + segs.join("/");
  }

  function buildTextSelector(el) {
    const t = safeText(el, 80);
    if (!t) return "";
    const esc = t.replace(/"/g, '\\"');
    return `text="${esc}"`;
  }

  function buildAriaSelector(el) {
    let role = el.getAttribute("role") || el.tagName.toLowerCase();
    const badRoles = { path: 1, svg: 1, g: 1, div: 1, span: 1 };
    if (badRoles[role]) {
      role = el.tagName.toLowerCase();
    }
    const name =
      el.getAttribute("aria-label") ||
      el.getAttribute("name") ||
      safeText(el, 60);
    if (!name) return `[role="${role}"]`;
    const esc = name.replace(/"/g, '\\"');
    return `[role="${role}"][name="${esc}"]`;
  }

  function nearestForm(el) {
    let n = el;
    while (n) {
      if (n.tagName && n.tagName.toLowerCase() === "form") {
        const id = n.id ? "#" + n.id : "";
        const nm = n.getAttribute("name") || "";
        return `form${id}${nm ? "[name=" + JSON.stringify(nm) + "]" : ""}`;
      }
      n = n.parentElement;
    }
    return null;
  }

  function parentSummary(el) {
    const p = el && el.parentElement;
    if (!p) return "";
    const tag = p.tagName.toLowerCase();
    const id = p.id ? "#" + p.id : "";
    const role = p.getAttribute("role");
    const r = role ? `[role=${role}]` : "";
    return `${tag}${id}${r}`;
  }

  function siblingSummaries(el, limit) {
    const p = el && el.parentElement;
    if (!p) return [];
    const out = [];
    for (const c of p.children) {
      if (c === el) continue;
      if (c.nodeType !== 1) continue;
      const tag = c.tagName.toLowerCase();
      const tid = c.id ? "#" + c.id : "";
      const txt = safeText(c, 40);
      out.push(`${tag}${tid}:${txt}`);
      if (out.length >= limit) break;
    }
    return out;
  }

  function indexInParent(el) {
    const p = el && el.parentElement;
    if (!p) return 0;
    return Array.prototype.indexOf.call(p.children, el);
  }

  function pickAnchors(el) {
    const anchors = [];
    const rect = el.getBoundingClientRect();
    const candidates = Array.from(
      document.querySelectorAll(
        "main,nav,header,footer,[role=main],[role=navigation],[role=dialog],[aria-modal=true],h1,h2,h3,[data-testid],[data-section-title]"
      )
    ).slice(0, anchorCandMax);
    for (const c of candidates) {
      if (!c || c === el) continue;
      const r = c.getBoundingClientRect();
      let relation = "inside";
      if (c.contains && c.contains(el)) {
        relation = "inside";
      } else if (rect.top >= r.bottom) {
        relation = "below";
      } else if (rect.bottom <= r.top) {
        relation = "above";
      } else {
        relation = "inside";
      }
      const label = (
        c.getAttribute("aria-label") ||
        safeText(c, 60) ||
        c.tagName.toLowerCase()
      ).slice(0, 120);
      anchors.push({ element: label, relation });
      if (anchors.length >= 4) break;
    }
    if (!anchors.length && el.parentElement) {
      anchors.push({ element: parentSummary(el), relation: "inside" });
    }
    return anchors;
  }

  function normalizedText(el) {
    return safeText(el, 500).toLowerCase();
  }

  function intentHint(tag, type, role, _text) {
    const t = (type || "").toLowerCase();
    const r = (role || "").toLowerCase();
    if (t === "submit") return "commit_form";
    if (t === "search") return "search_query";
    if (r === "link" || tag === "a") return "navigate";
    if (tag === "button" || r === "button") return "activate_control";
    if (tag === "input" || tag === "textarea") return "provide_input";
    if (tag === "select") return "choose_option";
    return "interact";
  }

  function serializeTarget(el, actionKind, value) {
    const tag = (el.tagName && el.tagName.toLowerCase()) || "unknown";
    const id = el.id || null;
    const classes = el.classList ? Array.from(el.classList) : [];
    const innerText = safeText(el, 2000);
    const role = el.getAttribute("role") || (tag === "a" ? "link" : null);
    const aria = el.getAttribute("aria-label");
    const name = el.getAttribute("name");
    const inputType = el.getAttribute("type");
    const rect = el.getBoundingClientRect();
    const scrollX = window.scrollX || window.pageXOffset || 0;
    const scrollY = window.scrollY || window.pageYOffset || 0;
    const viewport = `${Math.round(window.innerWidth)}x${Math.round(window.innerHeight)}`;
    const scroll_position = `${Math.round(scrollX)},${Math.round(scrollY)}`;
    // Viewport-relative box so Python can crop the viewport screenshot deterministically.
    const bbox = {
      x: Math.max(0, Math.round(rect.left)),
      y: Math.max(0, Math.round(rect.top)),
      w: Math.max(0, Math.round(rect.width)),
      h: Math.max(0, Math.round(rect.height)),
    };
    const semantic = {
      normalized_text: normalizedText(el),
      role: role || tag,
      input_type: inputType,
      intent_hint: intentHint(tag, inputType, role, innerText.toLowerCase()),
    };
    const selectors = {
      css: buildCssPath(el),
      xpath: buildXPath(el),
      text_based: buildTextSelector(el),
      aria: buildAriaSelector(el),
    };
    const context = {
      parent: parentSummary(el),
      siblings: siblingSummaries(el, siblingsMax),
      index_in_parent: indexInParent(el),
      form_context: nearestForm(el),
    };
    const anchors = pickAnchors(el);
    const page = { url: location.href, title: document.title || "" };
    const before = pageFingerprint();
    return {
      action: {
        action: actionKind,
        timestamp: new Date().toISOString(),
        value: value == null ? null : String(value),
      },
      target: {
        tag,
        id,
        classes,
        inner_text: innerText,
        role,
        aria_label: aria,
        name,
      },
      selectors,
      context,
      semantic,
      anchors,
      visual_placeholder: {
        bbox,
        viewport,
        scroll_position,
      },
      page,
      state_probe: { before },
    };
  }

  function report(payload) {
    const fn = window["__skillReport"];
    if (typeof fn !== "function") return;
    return fn(payload);
  }

  function finalizeState(payload) {
    const after = pageFingerprint();
    payload.state_change = {
      before: payload.state_probe.before,
      after,
    };
    delete payload.state_probe;
    return report(payload);
  }

  let inputTimer = null;
  let lastInputEl = null;

  function scheduleInputFlush(el) {
    lastInputEl = el;
    if (inputTimer) clearTimeout(inputTimer);
    inputTimer = setTimeout(() => {
      inputTimer = null;
      const target = lastInputEl;
      if (!target) return;
      const isPassword = target.getAttribute("type") === "password";
      const raw = "value" in target ? target.value : "";
      const value = isPassword ? "{{REDACTED}}" : raw;
      const p = serializeTarget(target, "type", value);
      p.action.value = value;
      requestAnimationFrame(() => finalizeState(p));
    }, inputDebounceMs);
  }

  document.addEventListener(
    "click",
    (ev) => {
      let el = ev.target && ev.target.nodeType === 1 ? ev.target : ev.target && ev.target.parentElement;
      if (!el || el.nodeType !== 1) return;
      const resolved = resolveMeaningfulTarget(el);
      if (!resolved) return;
      const p = serializeTarget(resolved, "click", null);
      requestAnimationFrame(() => finalizeState(p));
    },
    true
  );

  document.addEventListener(
    "change",
    (ev) => {
      const el = ev.target;
      if (!el || el.nodeType !== 1) return;
      const tag = el.tagName.toLowerCase();
      if (tag === "select") {
        const val = "value" in el ? el.value : null;
        const p = serializeTarget(el, "select", val);
        requestAnimationFrame(() => finalizeState(p));
        return;
      }
      if (tag === "input" || tag === "textarea") {
        scheduleInputFlush(el);
      }
    },
    true
  );

  document.addEventListener(
    "input",
    (ev) => {
      const el = ev.target;
      if (!el || el.nodeType !== 1) return;
      const tag = el.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea") {
        scheduleInputFlush(el);
      }
    },
    true
  );

  let scrollTimer = null;
  window.addEventListener(
    "scroll",
    () => {
      if (scrollTimer) clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        scrollTimer = null;
        const el = document.documentElement;
        const p = serializeTarget(el, "scroll", null);
        p.visual_placeholder.bbox = { x: 0, y: 0, w: 0, h: 0 };
        finalizeState(p);
      }, scrollDebounceMs);
    },
    { passive: true }
  );
})();
