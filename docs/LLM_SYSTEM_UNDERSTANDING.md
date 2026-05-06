# 🧠 Conxa System Understanding Guide (For LLMs & Humans)

## System Purpose
Transform unstructured screen recordings into structured, self-healing automation skills using multi-stage LLM enrichment and a 4-layer recovery mechanism.

---

## 📊 The 7-Stage Pipeline

```
Stage 1    →  Stage 2          →  Stage 3          →  Stage 4       →  Stage 5            →  Stage 6          →  Stage 7
RECORDING     PIPELINE            LLM                HUMAN           COMPILATION          PACKAGING          EXECUTION
             PROCESSING          ENRICHMENT         EDITING          & VALIDATION         & GENERATION       & RECOVERY

Raw Events → Normalized Events → Enriched Events → Refined Events → Compiled Actions → Skill Package → Executable Skill
             (cleaned)         (with intent)     (user-corrected) (w/ fallbacks)      (w/ recovery)      (self-healing)
```

---

## 🎯 Core Data Transformations

### Raw Event (Post-Recording)
Input from browser automation:
```json
{
  "action": {"action": "click", "button": "left"},
  "target": {"tag": "button", "inner_text": "Submit", "classes": ["btn"]},
  "selectors": {"css": "button.btn", "xpath": "//button"},
  "page": {"url": "https://...", "title": "Page Title"},
  "visual": {"full_screenshot": "path/to/image.jpg"}
}
```

### Enriched Event (After LLM Processing)
Added semantic meaning:
```json
{
  "semantic": {
    "normalized_text": "submit",
    "llm_intent": "submit_login_form",      ← FROM LLM
    "confidence": 0.98
  }
}
```

### Compiled Action (Ready for Execution)
With recovery metadata:
```json
{
  "id": "step_1",
  "action": "click",
  "selector": "button#submit",               ← L1 Primary
  "selector_confidence": 0.95,
  "selectors_fallback": ["button.btn"],     ← L1 Alternatives
  "validation": {"type": "url_contains", "value": "/dashboard"}
}
```

### Recovery Entry (Packaged with Execution)
Complete recovery metadata for self-healing:
```json
{
  "step_id": 1,
  "intent": "submit_login_form",
  "selector_context": {
    "primary": "button#submit",              ← L1: Primary selector
    "alternatives": ["button.btn", "..."]   ← L1: Fallback selectors
  },
  "anchors": [                               ← L2: Text anchors
    {"text": "Submit", "priority": 1.0},
    {"text": "Send", "priority": 0.8}
  ],
  "fallback": {                              ← L3: Text variants
    "text_variants": ["submit", "send"],
    "role": "button"
  },
  "visual_ref": "Image_1.jpg",               ← L4: Vision metadata
  "visual_metadata": {"available": true}
}
```

---

## 🔄 The 4-Layer Self-Healing Recovery Mechanism

**When Action Fails:** Conxa tries 4 layers sequentially to recover.

### Layer 1: Selector Context (Instant)
**Strategy:** Try alternative CSS/XPath selectors
```
Try: primary selector "button#submit"
  → Failed (element not found)
Try: alternative[0] "button.btn-primary"
  → Success ✅
```
- **Timeout:** None (instant DOM query)
- **Success Rate:** 60-70%
- **When:** First attempt for any failed action

### Layer 2: Text Anchors (Instant)
**Strategy:** Search using priority-scored text anchors
```
Try: "Submit" (priority 1.0)
  → Found element with text "Submit" ✅
```
- **Timeout:** None (instant text search)
- **Success Rate:** 50-60%
- **When:** If L1 fails

### Layer 3: Text Fallback Variants (Instant)
**Strategy:** Try normalized text alternatives + role hints
```
Try: "submit" (lowercase)
  → Found <button>submit</button> ✅
```
- **Timeout:** None (instant normalized search)
- **Success Rate:** 40-50%
- **When:** If L1 & L2 fail

### Layer 4: Vision Recovery (120s timeout)
**Strategy:** Vision LLM analyzes screenshot to find element
```
Screenshot → Vision LLM → Detects all buttons → Scores by intent → Returns best match ✅
```
- **Timeout:** 120 seconds (multimodal inference)
- **Success Rate:** 75-85%
- **When:** If L1-L3 all fail
- **Model:** Claude Vision or equivalent

### Recovery Success Rates
- **Layers 1-3 combined:** ~80% of failures (instant)
- **Layer 4 (vision):** ~15% additional (120s)
- **Total combined:** ~95% recovery success

---

## 🔑 Key Concepts for LLM Understanding

### Intent Ontology
Semantic labels extracted by LLM:
- `submit_form` → Click form submit button
- `fill_email_field` → Type into email input
- `fill_password_field` → Type into password input
- `navigate_to_page` → Change URL
- `select_dropdown_option` → Choose from dropdown

### Selector Scoring
How selectors are ranked by stability:
| Type | Score | Stability |
|------|-------|-----------|
| ID-based | 0.95 | Most stable (rarely change) |
| Class-based | 0.75 | Medium (may change) |
| Attribute | 0.70 | Medium-low |
| XPath | 0.65 | Fragile |
| Text-based | 0.45 | Most fragile |

**Strategy:** Use highest-scoring selector as primary, others as L1 fallbacks.

### Retry Attempts
- **Element actions** (click, fill, select): 2 total attempts
- **Navigate/Check actions**: 3 total attempts
- **Per attempt:** Exhausts L1 → L2 → L3 → L4 sequentially

### Validation Types
Criteria to verify action success:
- `url_contains` → Check URL changed
- `element_visible` → Element appeared on page
- `text_present` → Specific text visible
- `element_hidden` → Element disappeared
- `element_enabled` → Button is clickable

---

## 🧠 LLM Integration Points

### Point 1: Semantic Enrichment (Pipeline Stage 3)
**When:** Processing raw events during pipeline
**Input:** Element text + element type + page context
**Output:** Intent label + confidence score (0.0-1.0)
**Timeout:** 2 seconds (text only)

### Point 2: Vision Recovery (Execution Stage 7, Layer 4)
**When:** All other recovery layers failed
**Input:** Screenshot bytes + original intent + failed selectors
**Output:** Detected element selector + bounding box + confidence
**Timeout:** 120 seconds (multimodal, expensive)

---

## 📁 File Organization

### Backend (Python/FastAPI)
```
app/
├── recorder/         # Browser automation & event capture
│   ├── session.py   # Main recording coordinator
│   └── bridge.js    # JavaScript integration
├── pipeline/        # Event normalization & processing
│   ├── run.py       # Orchestration
│   ├── normalize.py # Schema normalization
│   └── enrich.py    # Semantic enrichment
├── llm/            # LLM integrations (Claude API)
│   ├── semantic_llm.py      # Intent extraction
│   ├── vision_llm.py        # Vision recovery
│   └── recovery_llm.py      # Failure recovery
├── compiler/       # Action compilation & validation
│   ├── action_semantics.py  # Action extraction
│   └── selector_score.py    # Selector ranking
├── services/       # High-level operations
│   └── skill_pack_builder.py # Package generation
└── models/         # Data models (events.py)
```

### Frontend (Next.js/React)
```
frontend/
├── app/
│   ├── (protected)/  # Authenticated routes
│   ├── workflows/    # Workflow editing interface
│   └── api/          # API route handlers (proxy to backend)
├── src/
│   ├── components/   # Reusable UI components
│   │   └── StepEditorPanel.tsx  # Step editor
│   ├── services/     # API wrappers (axios)
│   └── lib/          # Utility functions
```

---

## ⚙️ Configuration & Timeouts

### Critical Environment Variables
```bash
# LLM Configuration
SKILL_LLM_API_KEY=sk-ant-...
SKILL_LLM_TIMEOUT_MS=2000              # Text LLM timeout
SKILL_LLM_VISION_TIMEOUT_MS=120000     # Vision LLM timeout

# Recording & Storage
SKILL_SCREENSHOT_JPEG_QUALITY=80
SKILL_DATA_DIR=/data

# Authentication (Clerk)
SKILL_CLERK_ISSUER=...
SKILL_CLERK_JWKS_URL=...
```

### Timing Defaults for Actions
```json
{
  "click": {"wait_before": 0, "timeout": 5000, "wait_after": 500},
  "type": {"wait_before": 0, "timeout": 5000, "wait_after": 300},
  "navigate": {"wait_before": 0, "timeout": 10000, "wait_after": 2000},
  "scroll": {"wait_before": 0, "timeout": 3000, "wait_after": 500}
}
```

---

## 🚀 Execution Flow with Self-Healing

```
1. Load skill definition from skills.json
2. Launch Playwright browser
3. For each compiled step:
   a. Find element using primary selector
   b. If not found → Try L1 alternatives
   c. Execute action (click, type, etc.)
   d. Wait for state change
   e. Check validation criteria
   f. If failed:
      → Try L2 text anchors
      → Try L3 text variants
      → Try L4 vision recovery
   g. Continue to next step or fail
4. Return results (success, output, errors)
```

---

## 🐛 Common Failure Scenarios & Recovery

### Scenario 1: Simple Selector Change
```
Attempt: Click "button#submit"
Result: Not found
L1 Recovery: Try "button.btn-primary" → Success ✅
```

### Scenario 2: Text Changed
```
Attempt: Click button with text "Submit"
Result: Text not found
L2 Recovery: Try "Send" (anchor alternative) → Success ✅
```

### Scenario 3: UI Redesigned (Major Change)
```
Attempt: All L1-L3 fail
L4 Vision Recovery:
  1. Analyze current screenshot
  2. Detect all buttons
  3. Find button with intent "submit_form"
  4. Use new element location → Success ✅
```

### Scenario 4: Complete Failure
```
Result: All 4 layers exhausted
Status: ❌ Workflow failed
Action: Manual intervention needed, re-record workflow
```

---

## 📊 Performance Targets

| Metric | Target |
|--------|--------|
| Events per workflow | 20-50 |
| Pipeline processing | <200ms per event |
| LLM text enrichment | <2 seconds per event |
| LLM vision analysis | 30-120 seconds per image |
| Compilation | <500ms |
| Execution | 1-5 seconds per step |
| Recovery L1-L3 | Instant (microseconds) |
| Recovery L4 | 120 seconds max |
| **Combined recovery success** | **~95%** |

---

## 🔗 API Endpoints (LLM Perspective)

### For Recording
```
POST /api/v1/recordings
POST /api/v1/recordings/{id}/steps
```

### For Compilation
```
POST /api/v1/packages
POST /api/v1/packages/{id}/compile
```

### For Execution
```
POST /api/v1/skills/{skill_id}/execute
GET /api/v1/skills/{skill_id}
```

### User Management (Clerk Auth)
```
GET /api/v1/me
GET /api/v1/workspaces/current
```

---

## 💡 LLM Integration Strategy

When using Conxa from an LLM agent perspective:

### 1. Understanding the System
- Read `SYSTEM_REFERENCE_FOR_LLM.json` for structured data
- Use data structures as schema for validation
- Refer to retry policies when planning recovery

### 2. Executing Skills
```python
# Example: Agent executing a skill
skill_manifest = load_json("manifest.json")
execution_plan = skill_manifest["entry"]["execution"]  # execution.json
recovery_plan = skill_manifest["entry"]["recovery"]     # recovery.json

# For each step, understand:
# - What is the intent? (from recovery_entry.intent)
# - What are the fallback strategies? (L1-L4)
# - What validates success? (from compiled step)
```

### 3. Handling Failures
```python
# Understand that recovery is automatic, but:
# - L1-L3 are instant (same millisecond)
# - L4 takes up to 120 seconds
# - Combined success rate is ~95%
# - If all fail, manual intervention needed
```

### 4. Planning Skill Combinations
```python
# Agent combines multiple skills:
# 1. Read each skill's manifest.json
# 2. Extract parameters (from input.json)
# 3. Understand recovery behavior
# 4. Plan execution order considering dependencies
# 5. Handle skill failures based on recovery rates
```

---

## 📚 Document Map for LLMs

| Document | Content | For LLMs |
|----------|---------|----------|
| `SYSTEM_REFERENCE_FOR_LLM.json` | Complete JSON schema | Parse for programmatic understanding |
| `QUICK_REFERENCE.md` | Cheat sheet with tables | Quick lookup of parameters/timeouts |
| `workflow-visualization.html` | Interactive visual guide | Human-friendly visualization |
| `ARCHITECTURE_DEEP_DIVE.md` | Detailed technical explanation | Deep understanding of each stage |
| `data-flow-guide.html` | Data transformations | Understand data evolution |
| `*.svg` diagrams | Visual flows (4-layer recovery, etc.) | Visual system architecture |

---

## 🎯 Summary for LLMs

**Key Understanding Points:**

1. **7-Stage Pipeline:** Raw events → Normalized → Enriched → Edited → Compiled → Packaged → Executed
2. **2 LLM Calls:** Semantic enrichment (2s) + Vision recovery (120s when needed)
3. **4-Layer Recovery:** L1-L3 instant (selectors, anchors, text) + L4 vision (120s)
4. **Retry Policy:** 2 attempts for clicks/fills, 3 for navigate/check
5. **Success Rates:** L1-L3 ~80%, L4 ~15%, Combined ~95%
6. **Data Structures:** Raw event → Compiled action → Recovery entry (complete recovery info)
7. **Intent Ontology:** Semantic labels for each action (submit_form, fill_email, etc.)

**When Using Conxa:**
- Always check `recovery_entry` for L1-L4 strategies
- Plan skill combinations using `manifest.json`
- Account for 120s vision recovery timeout in critical paths
- Validate inputs match skill parameter definitions
- Handle failures after all recovery layers exhausted

---

**Generated:** 2026-05-05  
**For:** LLM Agents & Developers  
**Version:** 1.0
