"""Multi-provider LLM router with cool-down, failover, and per-key rate-limit handling."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

from app.config import ProviderConfig, settings
from app.llm.client import (
    _chat_completions_url,
    _debug_log,
    _is_openai_compatible_endpoint,
    _normalize_openai_response,
    _openai_body_dict,
    _parse_json_object_content,
    _provider_top_level_error,
    _safe_error_snippet,
)


@dataclass
class PoolEntry:
    """Single (provider, endpoint, key, model) tuple in the router pool."""
    provider: str
    endpoint: str
    api_key: str
    text_model: str
    vision_model: str
    requests_sent: int = 0
    requests_429: int = 0
    last_used_at: float = 0.0
    cooled_until: float = 0.0


class LLMRouter:
    """Multi-provider LLM router with per-key cool-down and automatic failover."""

    def __init__(self):
        """Build the initial provider pool from enabled providers in settings."""
        self.pool: list[PoolEntry] = []
        self.cooldown_secs: int = settings.llm_router_cooldown_secs
        self.max_retries: int = settings.llm_router_max_retries
        self.request_timeout_ms: int = settings.llm_router_request_timeout_ms
        self.prefer_fast_for_text: bool = settings.llm_router_prefer_fast_for_text
        self._request_counter: int = 0
        self._last_lru_index: int = 0

        # Build pool from enabled providers
        for provider_cfg in settings.enabled_llm_providers():
            entry = PoolEntry(
                provider=provider_cfg.provider,
                endpoint=provider_cfg.endpoint,
                api_key=provider_cfg.api_key,
                text_model=provider_cfg.text_model,
                vision_model=provider_cfg.vision_model,
            )
            self.pool.append(entry)

    def _next_available_entry(self, *, for_vision: bool = False) -> PoolEntry | None:
        """Pick next available entry from pool using LRU, skipping cooled entries."""
        if not self.pool:
            return None

        now = time.monotonic()
        attempts = 0
        max_attempts = len(self.pool) * 2

        while attempts < max_attempts:
            self._last_lru_index = (self._last_lru_index + 1) % len(self.pool)
            entry = self.pool[self._last_lru_index]
            attempts += 1

            # Skip cooled entries
            if entry.cooled_until > now:
                continue

            # For vision tasks, skip entries without vision_model
            if for_vision and not entry.vision_model:
                continue

            return entry

        return None

    def route_text(
        self,
        task: str,
        payload: dict[str, Any],
        timeout_ms: int,
        *,
        error_detail: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Route a text-only LLM call to an available provider."""
        if not self.pool:
            raise RuntimeError(
                "No LLM providers enabled. Set at least one *_API_KEYS and "
                "*_ENABLED=true in .env (e.g. GROQ_API_KEYS=gsk_... + GROQ_ENABLED=true)."
            )

        for attempt in range(self.max_retries):
            entry = self._next_available_entry(for_vision=False)
            if entry is None:
                _debug_log("router: all providers cooled or exhausted")
                if error_detail:
                    error_detail.append("router: all providers cooled or exhausted")
                break

            result = self._call_provider(
                entry,
                task,
                payload,
                timeout_ms,
                error_detail=error_detail,
                attempt=attempt,
            )

            if result is not None:
                return result

            # Continue to next provider on failure
            _debug_log(f"router: retry {attempt + 1}/{self.max_retries} for task {task}")

        return None

    def route_vision(
        self,
        task: str,
        payload: dict[str, Any],
        timeout_ms: int,
        *,
        error_detail: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Route a vision-capable LLM call to an available provider."""
        if not self.pool:
            raise RuntimeError(
                "No LLM providers enabled. Set at least one *_API_KEYS and "
                "*_ENABLED=true in .env. Note: vision tasks require providers with a vision_model."
            )

        for attempt in range(self.max_retries):
            entry = self._next_available_entry(for_vision=True)
            if entry is None:
                _debug_log("router: no providers with vision support available")
                if error_detail:
                    error_detail.append("router: no providers with vision support available")
                break

            result = self._call_provider(
                entry,
                task,
                payload,
                timeout_ms,
                error_detail=error_detail,
                attempt=attempt,
            )

            if result is not None:
                return result

            # Continue to next provider on failure
            _debug_log(f"router: retry {attempt + 1}/{self.max_retries} for vision task {task}")

        return None

    def _call_provider(
        self,
        entry: PoolEntry,
        task: str,
        payload: dict[str, Any],
        timeout_ms: int,
        *,
        error_detail: list[str] | None = None,
        attempt: int = 0,
    ) -> dict[str, Any] | None:
        """Make a single HTTP request to a provider."""
        self._request_counter += 1
        req_id = self._request_counter
        now = time.monotonic()

        # Use provider-specific model, falling back to payload model
        model = payload.get("model")
        if not model:
            if task in {"anchor_vision", "vision_reasoning"}:
                model = entry.vision_model
            else:
                model = entry.text_model

        # Prepare payload with the selected model
        payload_with_model = dict(payload)
        payload_with_model["model"] = model

        _debug_log(
            f"router: request_start req_id={req_id} provider={entry.provider} "
            f"endpoint={entry.endpoint} model={model} task={task} attempt={attempt}"
        )

        # Build OpenAI-compatible request
        if not _is_openai_compatible_endpoint(entry.endpoint):
            _debug_log(f"router: endpoint not openai-compatible {entry.endpoint}")
            if error_detail:
                error_detail.append(f"endpoint not openai-compatible: {entry.endpoint}")
            return None

        ep = _chat_completions_url(entry.endpoint)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {entry.api_key}",
        }

        timeout_s = max(0.2, timeout_ms / 1000.0)

        try:
            raw_body = json.dumps(_openai_body_dict(task, payload_with_model, json_mode=True)).encode("utf-8")
            req = request.Request(ep, data=raw_body, headers=headers, method="POST")

            with request.urlopen(req, timeout=timeout_s) as res:
                raw = res.read().decode("utf-8")

            entry.requests_sent += 1
            entry.last_used_at = now

            data_raw = json.loads(raw)
            if not isinstance(data_raw, dict):
                msg = f"unexpected_json_root: {type(data_raw).__name__}"
                _debug_log(f"router: {msg}")
                if error_detail:
                    error_detail.append(msg)
                return None

            prov_msg = _provider_top_level_error(data_raw)
            if prov_msg:
                _debug_log(f"router: provider_error {prov_msg}")
                if error_detail:
                    error_detail.append(f"provider_error: {prov_msg}")
                return None

            data = _normalize_openai_response(data_raw)
            _debug_log(f"router: response_ok req_id={req_id} provider={entry.provider}")
            return data if isinstance(data, dict) else None

        except error.HTTPError as exc:
            bod = _decode_http_error_body(exc)
            snippet = _safe_error_snippet(bod or str(exc.reason or exc))

            # Handle 429 rate limit: cool this key
            if exc.code == 429:
                entry.requests_429 += 1
                entry.cooled_until = now + self.cooldown_secs
                msg = f"HTTPError 429 rate_limited (cooled {self.cooldown_secs}s): {snippet}"
                _debug_log(f"router: {msg}")
                if error_detail:
                    error_detail.append(msg)
                return None

            # Handle 401/403 auth errors: drop this key permanently
            if exc.code in {401, 403}:
                msg = f"HTTPError {exc.code} auth_failed (dropping key): {snippet}"
                _debug_log(f"router: {msg}")
                if error_detail:
                    error_detail.append(msg)
                # Remove this entry from pool
                if entry in self.pool:
                    self.pool.remove(entry)
                return None

            # Other HTTP errors: transient, retry
            msg = f"HTTPError {exc.code}: {snippet}"
            _debug_log(f"router: {msg}")
            if error_detail:
                error_detail.append(msg)
            return None

        except (error.URLError, TimeoutError, OSError) as exc:
            msg = f"{type(exc).__name__}: {exc}"
            _debug_log(f"router: transient_error {msg}")
            if error_detail:
                error_detail.append(msg)
            return None

        except (json.JSONDecodeError, ValueError) as exc:
            msg = f"{type(exc).__name__}: {exc}"
            _debug_log(f"router: parse_error {msg}")
            if error_detail:
                error_detail.append(msg)
            return None

    def stats(self) -> dict[str, Any]:
        """Return pool statistics for compile reports."""
        return {
            "pool_size": len(self.pool),
            "entries": [
                {
                    "provider": entry.provider,
                    "endpoint": entry.endpoint,
                    "requests_sent": entry.requests_sent,
                    "requests_429": entry.requests_429,
                    "cooled": entry.cooled_until > time.monotonic(),
                }
                for entry in self.pool
            ],
        }


def _decode_http_error_body(exc: error.HTTPError) -> str:
    """Decode error response body from HTTP exception."""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


# Global router instance
_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    """Get or initialize the global router."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
