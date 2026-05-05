const fs = require("fs");
const path = require("path");
const tracker = require("./tracker");

// layer 0 = crashed (all layers exhausted)
// layer 1 = selector alternatives / text-variant fallback
// layer 2 = anchors
// layer 3 = LLM intent recovery
// layer 4 = vision recovery

function skillDir(name) {
  return path.join(__dirname, "..", "skills", name);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function stepId(value) {
  const num = Number(value);
  return Number.isInteger(num) && num > 0 ? num : null;
}

function uniqueStrings(values) {
  const out = [];
  const seen = new Set();
  for (const value of values || []) {
    if (typeof value !== "string") continue;
    const clean = value.trim();
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

function loadRecoveryMap(skill) {
  if (!skill) return null;
  const filePath = path.join(skillDir(skill), "recovery.json");
  if (!fs.existsSync(filePath)) return null;
  try {
    return readJson(filePath);
  } catch (_) {
    return null;
  }
}

function getRecoveryEntry(ctx) {
  if (ctx && ctx.recoveryEntry && typeof ctx.recoveryEntry === "object") {
    return ctx.recoveryEntry;
  }
  const recovery = ctx && typeof ctx.recovery === "object" ? ctx.recovery : loadRecoveryMap(ctx && ctx.skill);
  if (!recovery || !Array.isArray(recovery.steps)) return null;
  const currentStep = stepId(ctx && ctx.step);
  if (currentStep == null) return null;
  return recovery.steps.find((entry) => stepId(entry && entry.step_id) === currentStep) || null;
}

function buildTextVariantSelectors(entry) {
  const fallback = entry && typeof entry.fallback === "object" ? entry.fallback : {};
  const variants = Array.isArray(fallback.text_variants) ? fallback.text_variants : [];
  return variants
    .map((text) => (typeof text === "string" && text.trim() ? `text=${JSON.stringify(text.trim())}` : ""))
    .filter(Boolean);
}

function runSelectorFallback(ctx, entry) {
  const selectorContext = entry && typeof entry.selector_context === "object" ? entry.selector_context : {};
  const primary = typeof selectorContext.primary === "string" ? selectorContext.primary : "";
  const alternatives = Array.isArray(selectorContext.alternatives) ? selectorContext.alternatives : [];
  const candidates = uniqueStrings([primary, ...alternatives, ...buildTextVariantSelectors(entry)]);
  if (!candidates.length) return null;
  return {
    layer: 1,
    strategy: "selector_fallback",
    candidates,
    recovery_entry: entry,
  };
}

function runAnchorFallback(ctx, entry) {
  const anchors = Array.isArray(entry && entry.anchors) ? entry.anchors : [];
  const fallback = entry && typeof entry.fallback === "object" ? entry.fallback : {};
  const target = entry && typeof entry.target === "object" ? entry.target : {};
  const role = typeof fallback.role === "string" && fallback.role.trim()
    ? fallback.role.trim()
    : (typeof target.role === "string" ? target.role.trim() : "");
  const texts = uniqueStrings(
    anchors
      .map((anchor) => (anchor && typeof anchor === "object" ? anchor.text : ""))
      .filter(Boolean)
  );
  if (!texts.length && !role) return null;
  return {
    layer: 2,
    strategy: "anchor_fallback",
    anchors: anchors
      .filter((anchor) => anchor && typeof anchor === "object" && typeof anchor.text === "string" && anchor.text.trim())
      .map((anchor) => ({
        text: anchor.text.trim(),
        priority: Number.isFinite(Number(anchor.priority)) ? Number(anchor.priority) : 1,
      })),
    role,
    recovery_entry: entry,
  };
}

function truncateText(value, maxLength) {
  const text = typeof value === "string" ? value : JSON.stringify(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

async function captureDomSnapshot(page) {
  if (!page || typeof page.evaluate !== "function") return "";
  try {
    return truncateText(await page.evaluate(() => {
      const visibleText = (node) => (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
      const elements = Array.from(document.querySelectorAll("button,a,input,textarea,select,[role],[aria-label],[placeholder],[data-testid]"))
        .slice(0, 120)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          return {
            tag: el.tagName.toLowerCase(),
            id: el.id || "",
            role: el.getAttribute("role") || "",
            name: el.getAttribute("name") || "",
            type: el.getAttribute("type") || "",
            text: visibleText(el).slice(0, 120),
            aria: el.getAttribute("aria-label") || "",
            placeholder: el.getAttribute("placeholder") || "",
            testid: el.getAttribute("data-testid") || "",
            visible: rect.width > 0 && rect.height > 0,
          };
        });
      return {
        url: location.href,
        title: document.title,
        body_text: visibleText(document.body).slice(0, 3000),
        elements,
      };
    }), 12000);
  } catch (_) {
    try {
      return truncateText(await page.content(), 12000);
    } catch (_) {
      return "";
    }
  }
}

async function captureScreenshotBase64(page) {
  if (!page || typeof page.screenshot !== "function") return "";
  try {
    const buffer = await page.screenshot({ type: "jpeg", quality: 45, fullPage: false, timeout: 2000 });
    return buffer.toString("base64");
  } catch (_) {
    return "";
  }
}

function responseText(data) {
  if (typeof data.output_text === "string") return data.output_text;
  const chunks = [];
  for (const item of Array.isArray(data.output) ? data.output : []) {
    for (const part of Array.isArray(item.content) ? item.content : []) {
      if (typeof part.text === "string") chunks.push(part.text);
    }
  }
  return chunks.join("\n");
}

function parseLlmSelectors(text) {
  if (!text) return [];
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) return [];
  try {
    const parsed = JSON.parse(match[0]);
    return uniqueStrings(Array.isArray(parsed.selectors) ? parsed.selectors : []);
  } catch (_) {
    return [];
  }
}

async function runLlmIntentRecovery(ctx, entry) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey || !ctx || !ctx.page) return null;

  const [domResult, screenshotResult] = await Promise.allSettled([
    captureDomSnapshot(ctx.page),
    captureScreenshotBase64(ctx.page),
  ]);
  const dom = domResult.status === "fulfilled" ? domResult.value : "";
  const screenshot = screenshotResult.status === "fulfilled" ? screenshotResult.value : "";

  const prompt = [
    "Suggest Playwright selectors for recovering a failed browser automation step.",
    "Return only JSON: {\"selectors\":[\"selector1\",\"selector2\"]}.",
    "Prefer robust selectors: role selectors, text selectors, input attributes, aria labels, placeholders, data-testid.",
    `Error: ${truncateText(ctx.error || "", 2000)}`,
    `Recovery entry: ${truncateText(entry || {}, 4000)}`,
    `Current DOM summary: ${dom}`,
  ].join("\n\n");

  const content = [{ type: "input_text", text: prompt }];
  if (screenshot) {
    content.push({ type: "input_image", image_url: `data:image/jpeg;base64,${screenshot}` });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Number(process.env.CONXA_LLM_RECOVERY_TIMEOUT_MS) || 8000);
  try {
    const response = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: process.env.OPENAI_MODEL || "gpt-4o-mini",
        input: [{ role: "user", content }],
        temperature: 0,
        max_output_tokens: 200,
      }),
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const selectors = parseLlmSelectors(responseText(await response.json()));
    if (!selectors.length) return null;
    return {
      layer: 3,
      strategy: "selector_fallback",
      candidates: selectors,
      recovery_entry: entry,
    };
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function resolveVisualRef(ctx, entry) {
  const visualRef = entry && typeof entry.visual_ref === "string" ? entry.visual_ref.trim() : "";
  if (!visualRef) return "";
  if (path.isAbsolute(visualRef)) return visualRef;
  return path.join(skillDir(ctx && ctx.skill), visualRef);
}

async function runVisionRecovery(ctx, entry) {
  const page = ctx && ctx.page;
  const visualPath = resolveVisualRef(ctx, entry);
  if (!page || !visualPath || !fs.existsSync(visualPath)) return null;

  let current;
  try {
    current = ctx.currentScreenshot || await page.screenshot({ type: "png", scale: "css", fullPage: false, timeout: 2000 });
  } catch (_) {
    return null;
  }

  const target = entry && typeof entry.target === "object" ? entry.target : {};
  const fallback = entry && typeof entry.fallback === "object" ? entry.fallback : {};
  const payload = {
    currentDataUrl: `data:image/png;base64,${Buffer.from(current).toString("base64")}`,
    refDataUrl: `data:image/${path.extname(visualPath).toLowerCase() === ".png" ? "png" : "jpeg"};base64,${fs.readFileSync(visualPath).toString("base64")}`,
    targetText: typeof target.text === "string" ? target.text.trim() : "",
    targetRole: typeof target.role === "string" ? target.role.trim() : "",
    fallbackRole: typeof fallback.role === "string" ? fallback.role.trim() : "",
  };

  let candidates = [];
  try {
    candidates = await page.evaluate(async ({ currentDataUrl, refDataUrl, targetText, targetRole, fallbackRole }) => {
      const loadImage = (src) => new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = src;
      });
      const [current, reference] = await Promise.all([loadImage(currentDataUrl), loadImage(refDataUrl)]);
      const scale = Math.min(1, 180 / Math.max(current.width, current.height, reference.width, reference.height));
      const width = Math.max(1, Math.floor(Math.min(current.width, reference.width) * scale));
      const height = Math.max(1, Math.floor(Math.min(current.height, reference.height) * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width * 2;
      canvas.height = height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.drawImage(current, 0, 0, width, height);
      context.drawImage(reference, width, 0, width, height);
      const a = context.getImageData(0, 0, width, height).data;
      const b = context.getImageData(width, 0, width, height).data;
      const changed = new Uint8Array(width * height);
      for (let i = 0, p = 0; i < a.length; i += 4, p++) {
        changed[p] = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) > 42 ? 1 : 0;
      }

      const components = [];
      const queue = [];
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const start = y * width + x;
          if (!changed[start]) continue;
          changed[start] = 0;
          let minX = x, maxX = x, minY = y, maxY = y, count = 0;
          queue.length = 0;
          queue.push(start);
          for (let q = 0; q < queue.length; q++) {
            const idx = queue[q];
            const cx = idx % width;
            const cy = (idx / width) | 0;
            count++;
            if (cx < minX) minX = cx;
            if (cx > maxX) maxX = cx;
            if (cy < minY) minY = cy;
            if (cy > maxY) maxY = cy;
            const next = [idx - 1, idx + 1, idx - width, idx + width];
            for (const ni of next) {
              if (ni < 0 || ni >= changed.length || !changed[ni]) continue;
              const nx = ni % width;
              if ((ni === idx - 1 || ni === idx + 1) && Math.abs(nx - cx) !== 1) continue;
              changed[ni] = 0;
              queue.push(ni);
            }
          }
          if (count >= 6) components.push({ minX, maxX, minY, maxY, count });
        }
      }

      const needle = String(targetText || "").toLowerCase();
      const wantedRole = String(fallbackRole || targetRole || "").toLowerCase();
      const seen = new Set();
      const out = [];
      const add = (selector) => {
        if (selector && !seen.has(selector)) {
          seen.add(selector);
          out.push(selector);
        }
      };
      const attr = (value) => String(value).replace(/["\\]/g, "\\$&");
      const textOf = (el) => (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ");
      const selectorsFor = (el) => {
        const tag = el.tagName.toLowerCase();
        const id = el.getAttribute("id");
        const testId = el.getAttribute("data-testid");
        const name = el.getAttribute("name");
        const aria = el.getAttribute("aria-label");
        const placeholder = el.getAttribute("placeholder");
        const text = textOf(el);
        if (id) add(`#${CSS.escape(id)}`);
        if (testId) add(`[data-testid="${attr(testId)}"]`);
        if (name) add(`${tag}[name="${attr(name)}"]`);
        if (aria) add(`${tag}[aria-label="${attr(aria)}"]`);
        if (placeholder) add(`${tag}[placeholder="${attr(placeholder)}"]`);
        if (wantedRole && text) add(`role=${wantedRole}[name="${attr(text)}"]`);
        if (text) add(`text=${JSON.stringify(text)}`);
      };
      const score = (el, component) => {
        if (!el || el === document.body || el === document.documentElement) return -1;
        const rect = el.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) return -1;
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return -1;
        const text = textOf(el).toLowerCase();
        const role = (el.getAttribute("role") || el.tagName).toLowerCase();
        let value = component.count;
        if (needle && text.includes(needle)) value += 10000;
        if (wantedRole && role.includes(wantedRole)) value += 2000;
        if (/^(button|input|textarea|select|a)$/i.test(el.tagName)) value += 1000;
        return value;
      };

      const scaleX = current.width / width;
      const scaleY = current.height / height;
      components
        .sort((left, right) => right.count - left.count)
        .slice(0, 8)
        .map((component) => {
          const x = ((component.minX + component.maxX + 1) / 2) * scaleX;
          const y = ((component.minY + component.maxY + 1) / 2) * scaleY;
          let best = null;
          let bestScore = -1;
          for (const el of document.elementsFromPoint(x, y)) {
            for (let cur = el; cur && cur !== document.body; cur = cur.parentElement) {
              const value = score(cur, component);
              if (value > bestScore) {
                best = cur;
                bestScore = value;
              }
            }
          }
          return { best, bestScore };
        })
        .sort((left, right) => right.bestScore - left.bestScore)
        .forEach(({ best }) => {
          if (best) selectorsFor(best);
        });
      return out.slice(0, 12);
    }, payload);
  } catch (_) {
    return null;
  }

  const selectorCandidates = uniqueStrings(candidates);
  if (!selectorCandidates.length) return null;
  return {
    layer: 4,
    strategy: "selector_fallback",
    candidates: selectorCandidates,
    recovery_entry: entry,
  };
}

async function runLayer(layer, ctx) {
  tracker.send(`${ctx.skill}:${ctx.step}:${layer}`);
  const entry = getRecoveryEntry(ctx);
  switch (layer) {
    case 1:
      return runSelectorFallback(ctx, entry);
    case 2:
      return runAnchorFallback(ctx, entry);
    case 3:
      return runLlmIntentRecovery(ctx, entry);
    case 4:
      return runVisionRecovery(ctx, entry);
    default:
      throw new Error(`Unknown recovery layer: ${layer}`);
  }
}

async function runRecovery(ctx) {
  for (const layer of [1, 2, 3, 4]) {
    const result = await runLayer(layer, ctx);
    if (result) {
      return result;
    }
  }
  tracker.send(`${ctx.skill}:${ctx.step}:0`);
  throw new Error(`All recovery layers exhausted for ${ctx.skill}:${ctx.step}`);
}

module.exports = { runLayer, runRecovery };
