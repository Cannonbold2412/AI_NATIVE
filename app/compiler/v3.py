"""Skill Compiler V3 transforms: strict cleanup and dynamic validation mapping."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from app.compiler.action_semantics import action_name, is_editable_target, looks_like_submit
from app.compiler.selector_filters import is_dynamic_id, selector_passes_filters
from app.compiler.selector_score import ordered_selector_strings, rank_labeled_selector_candidates
from app.compiler.intent_access import get_effective_intent
from app.compiler.decision_layer import infer_compiled_validation
from app.compiler.validation_planner import infer_wait_for_shape
from app.compiler.wait_for_shape import is_wait_group, leaf_wait_type
from app.policy.bundle import get_policy_bundle

Step = dict[str, Any]


def _generic_anchors(policy: dict[str, Any] | None = None) -> set[str]:
    data = policy or get_policy_bundle().data
    sec = data.get("anchors") if isinstance(data.get("anchors"), dict) else {}
    raw = sec.get("generic_skip") or ["header", "h1", "h2", "h3", "title", "page"]
    return {str(x).strip().lower() for x in raw}


def _anchors_section(policy: dict[str, Any] | None) -> dict[str, Any]:
    pol = policy or get_policy_bundle().data
    sec = pol.get("anchors")
    return sec if isinstance(sec, dict) else {}


def _semantic_anchor_config(policy: dict[str, Any] | None) -> dict[str, Any]:
    sec = _anchors_section(policy)
    raw = sec.get("semantic_anchors")
    return raw if isinstance(raw, dict) else {}


def _default_phrase_stopwords() -> set[str]:
    return {
        "submit",
        "cancel",
        "close",
        "ok",
        "next",
        "continue",
        "button",
        "input",
        "click",
        "loading",
        "save",
        "reset",
        "apply",
        "search",
    }


def _phrase_is_discriminative(phrase: str, sem_cfg: dict[str, Any], generic: set[str]) -> bool:
    p = " ".join(str(phrase).lower().split()).strip()
    if len(p) < int(sem_cfg.get("min_phrase_len", 3)):
        return False
    if p in generic:
        return False
    stops = _default_phrase_stopwords() | {str(x).lower() for x in (sem_cfg.get("phrase_stopwords") or []) if x}
    if p in stops:
        return False
    min_chars = int(sem_cfg.get("min_unlisted_phrase_chars", 6))
    if len(p) >= min_chars:
        return True
    if " " in p and len(p.replace(" ", "")) >= int(sem_cfg.get("min_multiword_body_chars", 4)):
        return True
    if any(ch in p for ch in "#.[]:@/"):
        return True
    return False


def semantic_context_anchor_candidates(
    context: dict[str, Any],
    semantic: dict[str, Any] | None,
    target: dict[str, Any] | None,
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Short, deterministic relational phrases from DOM context + target (not generic buckets)."""
    sem_cfg = _semantic_anchor_config(policy)
    if not bool(sem_cfg.get("enabled", True)):
        return []
    pol = policy or get_policy_bundle().data
    generic = _generic_anchors(pol)
    max_len = int(sem_cfg.get("max_phrase_len", 56))
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(element: str, relation: str) -> None:
        el = " ".join(str(element).lower().split()).strip()[:max_len]
        rel = str(relation or "near").strip().lower()
        if rel not in {"inside", "above", "below", "near"}:
            rel = "near"
        if not _phrase_is_discriminative(el, sem_cfg, generic):
            return
        key = (el, rel)
        if key in seen:
            return
        seen.add(key)
        out.append({"element": el, "relation": rel})

    ctx = context if isinstance(context, dict) else {}
    tgt = target if isinstance(target, dict) else {}
    sem = semantic if isinstance(semantic, dict) else {}

    parent = str(ctx.get("parent") or "").strip()
    if parent:
        _add(parent, "inside")

    fc = str(ctx.get("form_context") or "").strip()
    if fc and fc.lower() != parent.lower():
        _add(fc, "near")

    for key in ("aria_label", "placeholder", "name"):
        raw = str(tgt.get(key) or "").strip()
        if raw:
            _add(raw, "near")

    inner = str(tgt.get("inner_text") or "").strip()
    if inner:
        _add(inner[:max_len], "near")

    norm = str(sem.get("normalized_text") or "").strip()
    if norm and norm.lower() != inner.lower():
        _add(norm[:max_len], "near")

    sib_max = int(sem_cfg.get("max_sibling_anchor_candidates", 2))
    for sib in (ctx.get("siblings") or [])[: max(0, sib_max)]:
        sx = str(sib).strip()
        if sx and len(sx) <= max_len + 20:
            _add(sx[:max_len], "near")

    return out


def semantic_anchor_phrase_kept(element: str, policy: dict[str, Any] | None = None) -> bool:
    """True when element is an allowlisted unlisted semantic phrase (for recovery / policy filters)."""
    pol = policy or get_policy_bundle().data
    sem_cfg = _semantic_anchor_config(pol)
    if not bool(sem_cfg.get("allow_unlisted_phrases", True)):
        return False
    return _phrase_is_discriminative(str(element or ""), sem_cfg, _generic_anchors(pol))


def _target_key(step: Step) -> str:
    target = step.get("target") or {}
    selectors = step.get("selectors") or {}
    return "|".join(
        [
            str(selectors.get("aria") or ""),
            str(selectors.get("text_based") or ""),
            str(selectors.get("css") or ""),
            str(target.get("name") or ""),
            str(target.get("id") or ""),
            str(target.get("tag") or ""),
            str(target.get("placeholder") or ""),
        ]
    )


def _event_value(step: Step) -> str:
    action = step.get("action") or {}
    if isinstance(action, dict):
        return str(action.get("value") or "")
    return ""


def _normalize_prep_click_to_focus(step: Step, policy: dict[str, Any]) -> Step:
    """Clicks on editable fields that are not submit behave like focus acquisition (optional via policy)."""
    wf = policy.get("workflow") if isinstance(policy.get("workflow"), dict) else {}
    if not bool(wf.get("normalize_editable_click_to_focus", True)):
        return step
    if action_name(step).lower() != "click":
        return step
    if looks_like_submit(step, policy):
        return step
    if not is_editable_target(step):
        return step
    out = dict(step)
    ap = dict(out.get("action") or {})
    ap["action"] = "focus"
    out["action"] = ap
    return out


def _navigation_detected(prev_submit: Step, current: Step) -> bool:
    prev_url = str((prev_submit.get("page") or {}).get("url") or "")
    current_url = str((current.get("page") or {}).get("url") or "")
    if prev_url and current_url and prev_url != current_url:
        return True
    state_change = current.get("state_change") or {}
    before = str(state_change.get("before") or "")
    after = str(state_change.get("after") or "")
    return bool(before and after and before != after)


def _truncate_after_terminal_submit(policy: dict[str, Any]) -> bool:
    wf = policy.get("workflow") if isinstance(policy.get("workflow"), dict) else {}
    return bool(wf.get("truncate_after_terminal_submit", False))


def clean_steps(steps: list[Step], policy: dict[str, Any] | None = None) -> list[Step]:
    """Strict step cleanup for recorded workflows."""
    pol = policy or get_policy_bundle().data
    if not steps:
        return []
    cleaned: list[Step | None] = []
    last_type_index: dict[str, int] = {}
    pending_submit: Step | None = None
    use_submit_truncate = _truncate_after_terminal_submit(pol)
    for raw in steps:
        step = dict(raw)
        step = _normalize_prep_click_to_focus(step, pol)
        action = action_name(step)
        key = _target_key(step)

        # Optional legacy: drop anything after terminal submit unless navigation signal appears.
        if use_submit_truncate and pending_submit is not None:
            if _navigation_detected(pending_submit, step):
                pending_submit = None
            else:
                continue

        # Remove duplicate consecutive action.
        if cleaned and cleaned[-1] is not None:
            prev = cleaned[-1]
            prev_action = action_name(prev or {})
            prev_key = _target_key(prev or {})
            if action == prev_action and key == prev_key and prev is not None:
                if action == "type":
                    prev_payload = dict(prev.get("action") or {})
                    curr_payload = dict(step.get("action") or {})
                    if curr_payload.get("value") not in {None, ""}:
                        prev_payload["value"] = curr_payload.get("value")
                        prev["action"] = prev_payload
                continue

        # Merge noisy click/focus + type on same field.
        if action == "type" and cleaned and cleaned[-1] is not None:
            prev = cleaned[-1]
            if prev is not None and action_name(prev) in {"click", "focus"} and _target_key(prev) == key:
                cleaned.pop()

        # Later type on same field: merge value into the earlier step (preserve chronology).
        if action == "type" and key in last_type_index:
            old_idx = last_type_index[key]
            if 0 <= old_idx < len(cleaned) and cleaned[old_idx] is not None:
                old_step = cleaned[old_idx]
                if action_name(old_step) == "type" and _target_key(old_step) == key:
                    old_payload = dict(old_step.get("action") or {})
                    new_payload = dict(step.get("action") or {})
                    if new_payload.get("value") not in {None, ""}:
                        old_payload["value"] = new_payload.get("value")
                    old_step["action"] = old_payload
                    last_type_index[key] = old_idx
                    continue

        cleaned.append(step)
        if action == "type":
            last_type_index[key] = len(cleaned) - 1

        if use_submit_truncate and action == "click" and looks_like_submit(step, pol):
            pending_submit = step

    cleaned = [s for s in cleaned if s is not None]
    # Drop redundant post-entry clicks on the same editable target (focus already implied by typing).
    deduped: list[Step] = []
    for step in cleaned:
        prev_action = action_name(deduped[-1]).lower() if deduped else ""
        cur_action = action_name(step).lower()
        if deduped and cur_action in {"click", "focus"} and not looks_like_submit(step, pol):
            prev = deduped[-1]
            if (
                is_editable_target(step)
                and prev_action == "type"
                and _target_key(prev) == _target_key(step)
            ):
                continue
        deduped.append(step)
    cleaned = deduped

    # Optional legacy: remove trailing type steps after terminal submit if no navigation happened.
    if use_submit_truncate and pending_submit is not None:
        out: list[Step] = []
        for s in cleaned:
            out.append(s)
            if s is pending_submit:
                break
        return out
    return cleaned


def _synthetic_focus_before_type(type_step: Step) -> Step:
    """Minimal focus acquisition for the same target as a type (recording order preserved)."""
    out = dict(type_step)
    ap = dict(out.get("action") or {})
    ap["action"] = "focus"
    ap.pop("value", None)
    out["action"] = ap
    return out


def _same_target_focus_prereq(prev: Step | None, step: Step, policy: dict[str, Any]) -> bool:
    """True when the previous step already focuses/clicks the same field (non-submit)."""
    if prev is None:
        return False
    if _target_key(prev) != _target_key(step):
        return False
    pa = action_name(prev).lower()
    if pa == "focus":
        return True
    if pa == "click" and not looks_like_submit(prev, policy):
        return True
    return False


def sanitize_steps_preserving_order(steps: list[Step], policy: dict[str, Any] | None = None) -> list[Step]:
    """Keep compile order aligned with recording; insert focus only when type lacks same-target prep."""
    if not steps:
        return []
    pol = policy or get_policy_bundle().data
    wf = pol.get("workflow") if isinstance(pol.get("workflow"), dict) else {}
    insert_focus = bool(wf.get("synthetic_focus_before_type", True))
    out: list[Step] = []
    for step in steps:
        st = dict(step)
        action = action_name(st).lower()
        if insert_focus and action == "type" and is_editable_target(st):
            prev = out[-1] if out else None
            if not _same_target_focus_prereq(prev, st, pol):
                out.append(_synthetic_focus_before_type(st))
        out.append(st)
    return out


def fix_step_order(steps: list[Step], policy: dict[str, Any] | None = None) -> list[Step]:
    """Preserve recorded step order; only minimal focus-before-type inserts (no cross-field reorder)."""
    return sanitize_steps_preserving_order(steps, policy)


def rank_selectors(selectors: dict[str, Any], policy: dict[str, Any] | None = None) -> list[str]:
    pol = policy or get_policy_bundle().data
    return ordered_selector_strings(
        {
            "aria": selectors.get("aria"),
            "name": selectors.get("name"),
            "text_based": selectors.get("text_based"),
            "role": selectors.get("role"),
            "css": selectors.get("css"),
            "xpath": selectors.get("xpath"),
        },
        pol,
    )


def generate_stable_selector(element: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build stable selector set: policy-scored candidates (not a fixed name-before-css order)."""
    pol = policy or get_policy_bundle().data
    selectors = element.get("selectors") or {}
    target = element.get("target") or {}

    name = str(target.get("name") or "").strip()
    input_type = str((element.get("semantic") or {}).get("input_type") or target.get("type") or "").strip().lower()
    aria_label = str(target.get("aria_label") or "").strip()
    placeholder = str(target.get("placeholder") or "").strip()
    text_based = str(selectors.get("text_based") or "").strip()
    css = str(selectors.get("css") or "").strip()
    raw_id = str(target.get("id") or "").strip()
    id_selector = f"#{raw_id}" if raw_id else ""

    def _escape_attr(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    rows: list[tuple[str, str]] = []
    if name:
        rows.append(("name", f'input[name="{_escape_attr(name)}"]'))
    if input_type:
        rows.append(("css", f'input[type="{_escape_attr(input_type)}"]'))
    if aria_label:
        rows.append(("aria", f'[aria-label="{_escape_attr(aria_label)}"]'))
    if placeholder:
        rows.append(("css", f'[placeholder="{_escape_attr(placeholder)}"]'))
    if text_based and selector_passes_filters(text_based):
        rows.append(("text_based", text_based))
    if css and not is_dynamic_id(css) and selector_passes_filters(css):
        rows.append(("css", css))
    if id_selector and not is_dynamic_id(id_selector) and selector_passes_filters(id_selector):
        rows.append(("css", id_selector))

    unique = rank_labeled_selector_candidates(rows, pol)

    if not unique:
        fallback_name = str(target.get("tag") or "input").strip() or "input"
        unique = [fallback_name]
    return {
        "primary_selector": unique[0],
        "fallback_selectors": unique[1:],
    }


def clean_anchors(
    anchors: list[dict[str, Any]],
    context: dict[str, Any],
    policy: dict[str, Any] | None = None,
    *,
    target: dict[str, Any] | None = None,
    semantic: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pol = policy or get_policy_bundle().data
    sec = _anchors_section(pol)
    allowed = {str(x).strip().lower() for x in (sec.get("allowed_elements") or [])}
    generic = _generic_anchors(pol)
    sem_cfg = _semantic_anchor_config(pol)
    allow_unlisted = bool(sem_cfg.get("allow_unlisted_phrases", True))
    allow_sibling_fallback = bool(sem_cfg.get("allow_sibling_input_fallback", True))
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _push(element: str, relation: str, *, bypass_allowlist: bool = False) -> None:
        el = str(element or "").strip().lower()
        rel = str(relation or "inside").strip().lower()
        if rel not in {"inside", "above", "below", "near"}:
            rel = "inside"
        if not el or el in generic:
            return
        if not bypass_allowlist:
            if allowed and el not in allowed:
                return
        elif allow_unlisted:
            if allowed and el not in allowed and not _phrase_is_discriminative(el, sem_cfg, generic):
                return
        else:
            if allowed and el not in allowed:
                return
        key = (el, rel)
        if key in seen:
            return
        seen.add(key)
        out.append({"element": el, "relation": rel})

    for raw in anchors or []:
        _push((raw or {}).get("element") or "", (raw or {}).get("relation") or "inside")

    tgt = target if isinstance(target, dict) else {}
    sem = semantic if isinstance(semantic, dict) else {}
    for cand in semantic_context_anchor_candidates(context, sem, tgt, pol):
        _push(str(cand.get("element") or ""), str(cand.get("relation") or "near"), bypass_allowlist=True)

    if not out:
        parent = str(context.get("parent") or "").strip().lower()
        siblings = " ".join(str(s).strip().lower() for s in (context.get("siblings") or []))
        blob = f"{parent} {siblings}".strip()
        if blob:
            for element in sorted(allowed):
                if element in {"input", "sibling_input"}:
                    continue
                if element in blob:
                    _push(element, "inside")
            if any(k in blob for k in ("label", "placeholder", "for=")):
                _push("label", "near")

    if not out and context.get("siblings") and allow_sibling_fallback:
        _push("sibling_input", "near")
    return out


def optimize_scroll(step: Step) -> dict[str, Any] | str:
    if action_name(step) != "scroll":
        return action_name(step)
    return "scroll"


def scroll_payload(step: Step, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if action_name(step) != "scroll":
        return {}
    pol = policy or get_policy_bundle().data
    sd = pol.get("scroll_defaults") if isinstance(pol.get("scroll_defaults"), dict) else {}
    return {
        "direction": str(sd.get("direction", "down")),
        "delta": int(sd.get("delta", 150)),
    }


def _fingerprint(state: dict[str, Any]) -> str:
    payload = {
        "url": state.get("url") or "",
        "title": state.get("page_title") or "",
        "elements": state.get("visible_key_elements") or [],
        "texts": state.get("important_text_blocks") or [],
    }
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def capture_state_snapshot(step: Step, *, before: bool) -> dict[str, Any]:
    page = step.get("page") or {}
    target = step.get("target") or {}
    context = step.get("context") or {}
    selectors = step.get("selectors") or {}
    state_change = step.get("state_change") or {}
    state_text = str(state_change.get("before" if before else "after") or "")
    visible = [
        str(selectors.get("aria") or ""),
        str(selectors.get("text_based") or ""),
        str(selectors.get("css") or ""),
        str(target.get("tag") or ""),
    ] + [str(s) for s in (context.get("siblings") or [])[:6]]
    target_text = str(target.get("inner_text") or "").strip()
    if action_name(step) == "scroll":
        target_text = ""
    state = {
        "url": str(page.get("url") or ""),
        "page_title": str(page.get("title") or ""),
        "visible_key_elements": [x for x in visible if x],
        "important_text_blocks": [
            x
            for x in [target_text[:240], state_text.strip()[:240]]
            if x
        ][:4],
    }
    state["dom_fingerprint"] = _fingerprint(state)
    return state


def compare_state(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    b_elements = set(before.get("visible_key_elements") or [])
    a_elements = set(after.get("visible_key_elements") or [])
    b_text = set(before.get("important_text_blocks") or [])
    a_text = set(after.get("important_text_blocks") or [])
    n_new = sorted(a_elements - b_elements)
    n_rem = sorted(b_elements - a_elements)
    n_txt = sorted(a_text - b_text)
    strength = min(1.0, (len(n_new) + len(n_rem) + len(n_txt)) / 20.0)
    return {
        "url_changed": str(before.get("url") or "") != str(after.get("url") or ""),
        "dom_changed": str(before.get("dom_fingerprint") or "") != str(after.get("dom_fingerprint") or ""),
        "new_elements": n_new,
        "removed_elements": n_rem,
        "text_change": n_txt,
        "evidence_strength": strength,
    }


def validation_from_diff(
    action: str,
    intent: str,
    state_diff: dict[str, Any],
    timeout: int,
    *,
    page_url: str = "",
    source_step: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pol = policy or get_policy_bundle().data
    validation_step = source_step or {
        "action": {"action": action},
        "semantic": {"llm_intent": intent},
        "timing": {"timeout": timeout},
    }
    return infer_compiled_validation(validation_step, state_diff, page_url, pol)


def fix_validation(
    step: dict[str, Any],
    state_diff: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infer wait shape from action + observed diff (event-driven)."""
    pol = policy or get_policy_bundle().data
    sd = state_diff if isinstance(state_diff, dict) else {}
    return infer_wait_for_shape(step, sd, pol)


def _placeholder_leaf_ok(node: dict[str, Any]) -> bool:
    t = leaf_wait_type(node)
    if t in {"", "none"}:
        return True
    return t in {"url_change", "element_appear", "element_disappear", "intent_outcome", "dom_change"}


def _placeholder_tree_ok(node: dict[str, Any]) -> bool:
    """Recursive AND/OR placeholder (real executors should replace with browser checks)."""
    if is_wait_group(node):
        op = str(node.get("op") or "").strip().lower()
        kids = [c for c in (node.get("conditions") or []) if isinstance(c, dict)]
        if not kids:
            return False
        if op == "and":
            return all(_placeholder_tree_ok(c) for c in kids)
        if op == "or":
            return any(_placeholder_tree_ok(c) for c in kids)
        return False
    return _placeholder_leaf_ok(node)


def wait_for_condition(step: dict[str, Any], timeout: int = 8000) -> bool:
    """Deterministic polling helper for execution-layer validators."""
    raw = ((step.get("validation") or {}).get("wait_for") or {})
    wf = dict(raw) if isinstance(raw, dict) else {}
    if not wf:
        return True
    deadline = time.monotonic() + max(100, int(timeout)) / 1000.0
    while time.monotonic() < deadline:
        time.sleep(0.05)
        if _placeholder_tree_ok(wf):
            return True
    return False

