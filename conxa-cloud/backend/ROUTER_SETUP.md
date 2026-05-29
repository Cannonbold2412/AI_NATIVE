# Multi-Provider LLM Router Setup

## Summary

Implemented a multi-provider LLM router with automatic failover, per-key cool-down, and support for up to 5 different free-tier LLM providers. This enables high-volume LLM use during compilation without hitting rate limits.

## What's New

### 1. Multi-Provider LLM Router (`app/llm/router.py`)
- Manages a pool of (provider, endpoint, key, model) tuples from enabled providers
- Routes text/vision calls via LRU + per-key cool-down on 429 errors
- Handles 401/403 (permanent drop), 429 (60s cool-down), other errors (retry)
- Tracks per-entry metrics: `requests_sent`, `requests_429`, `cooled_until`, `last_used_at`
- Skips text-only providers for vision tasks

### 2. Extended Configuration (`app/config.py`)
- Added 7 provider blocks pre-configured with latest free-tier models (May 2026):
  - **Groq** (enabled by default): 300+ tok/s, 30 req/min, text + vision
  - **Google AI Studio** (enabled): Best free-tier vision, 1500 req/day
  - **NVIDIA NIM** (enabled): 100+ free models, 40 req/min per model
  - **Cerebras** (disabled): Very fast text (2600+ tok/s), text-only
  - **Together AI** (disabled): 80+ free models, rate-limited
  - **OpenRouter** (disabled): Aggregator with free models, 50 req/day
  - **Mistral** (disabled): Text + Pixtral vision
- Each provider supports comma-separated API keys: `PROVIDER_API_KEYS=key1,key2,key3,key4,key5`
- Router behavior knobs: `LLM_ROUTER_COOLDOWN_SECS`, `MAX_RETRIES`, `REQUEST_TIMEOUT_MS`, `PREFER_FAST_FOR_TEXT`
- Backward compatible: if no provider enabled, falls back to legacy single-endpoint config

### 3. Router Integration (`app/llm/client.py`)
- Modified `call_llm()` to transparently use multi-provider router when available
- All existing LLM call sites (semantic_llm, intent_llm, recovery_llm, etc.) benefit automatically
- Graceful fallback on router error → single-endpoint config

### 4. LLM-Native Selector Generation (`app/compiler/llm_selector_generator_v2.py`)
- `generate_selector_with_objective_confidence()` generates high-confidence selectors
- Computes confidence from 3 objective signals (not LLM self-report):
  1. **DOM uniqueness** (0.4 max): How many elements match selector in recorded DOM
  2. **Self-consistency** (0.3 max): Agreement rate across N LLM calls (typically 5)
  3. **Visual verification** (0.3 max): [Future] Cross-frame visual confirmation
- Returns: selector + confidence (0.0–1.0) + breakdown + rationale
- If confidence < 0.50, returns empty selector (high-confidence only)
- Helper functions for DOM matching: `data-testid`, `aria-label`, `text` content, tags

## Usage

### 1. Configure API Keys

Copy `.env.example` to `.env` and fill in API keys (user accounts):

```bash
# One key per Gmail account (example: 5 keys across 5 Gmail accounts on Groq)
GROQ_API_KEYS=key1,key2,key3,key4,key5

# Single key for Google AI Studio
GOOGLE_AI_STUDIO_API_KEYS=your-api-key

# Multiple keys for NVIDIA NIM
NVIDIA_NIM_API_KEYS=nvapi-abc123,nvapi-def456
```

### 2. Enable/Disable Providers

```env
# Enable Groq, Google AI Studio, NVIDIA NIM (default)
GROQ_ENABLED=true
GOOGLE_AI_STUDIO_ENABLED=true
NVIDIA_NIM_ENABLED=true

# Disable others initially
CEREBRAS_ENABLED=false
TOGETHER_ENABLED=false
OPENROUTER_ENABLED=false
MISTRAL_ENABLED=false
```

### 3. Router Behavior (Optional Tuning)

```env
# Cool a key for 60s after hitting rate limit
LLM_ROUTER_COOLDOWN_SECS=60

# Retry up to 3 times before giving up
LLM_ROUTER_MAX_RETRIES=3

# Per-request timeout (30s)
LLM_ROUTER_REQUEST_TIMEOUT_MS=30000

# Prefer Groq/Cerebras for text-only (faster)
LLM_ROUTER_PREFER_FAST_FOR_TEXT=true
```

## Example: Recompiling with Multi-Provider Router

```bash
# Compile with 3 enabled providers, 5 keys each = 15 entries in pool
# Each LLM call tries the next available key in LRU order
# On 429 error, cools that key for 60s and tries the next
# With ~189 LLM calls per 21-step recording, distributes load across 15 keys

python scripts/compile_skill.py --session-id c3d7bd48-... --with-llm
```

Expected behavior:
- Pool stats in compile report show distribution: each key gets ~12-13 calls
- No `429_retry_exhausted` errors in `llm_router_stats`
- Compile finishes in reasonable time (not rate-limited)

## Future Work

- [ ] Video recording during recording phase (frames T-500ms, T-100ms, T+100ms, T+500ms per event)
- [ ] Frame extraction post-record + visual verification in selector generation
- [ ] Wire LLM-native selector generation into build.py (with fallback to heuristics)
- [ ] Input binding from visual context (label_text, placeholder, aria_label priority)
- [ ] Keyboard event preservation with recorded keys (e.g. value: "Enter" instead of {{text}})
- [ ] Compile report with confidence breakdown and warnings per step
- [ ] CLI option to toggle LLM-native generation vs heuristic approach

## Backward Compatibility

- If **no providers enabled** in .env, router pool is empty → automatically uses legacy single-endpoint config (SKILL_LLM_TEXT_ENDPOINT, SKILL_LLM_VISION_ENDPOINT)
- Existing deployments continue to work unchanged
- `.env.example` includes both multi-provider block (new) and legacy single-endpoint section (kept for compatibility)

## Known Limitations (Fixed by Future Commits)

- [ ] Selector generation not yet wired into compile phase (ready but not integrated)
- [ ] DOM uniqueness check requires full DOM snapshot (workaround: skip if not available)
- [ ] Visual verification placeholder (future: implement with video frames)
- [ ] No input binding derivation from visual context yet (future)
- [ ] No keyboard event key preservation yet (future)
