# Conxa: Complete Architecture Deep Dive

## Table of Contents
1. [System Overview](#system-overview)
2. [Recording Phase (Capture)](#recording-phase-capture)
3. [Pipeline Processing](#pipeline-processing)
4. [LLM Enrichment](#llm-enrichment)
5. [Human Editing](#human-editing)
6. [Workflow Compilation](#workflow-compilation)
7. [Skill Package Generation](#skill-package-generation)

---

## System Overview

Conxa is an AI-driven workflow automation platform that transforms real user interactions into executable skills through a multi-stage pipeline:

```
User Records Workflow → Raw Events Captured → Pipeline Cleaning → LLM Enrichment → Human Review & Edit → Skill Compilation → Executable Package
```

Each stage adds semantic meaning and validation until raw screen interactions become a production-ready automation skill.

---

## Recording Phase (Capture)

### What Happens During Recording

When a user records a workflow:

1. **Browser Automation**: Playwright opens a real browser instance (Chrome)
2. **Event Binding**: A JavaScript bridge (`bridge.js`) is injected into the page via `expose_binding`
3. **Event Capture**: All user interactions (clicks, typing, navigation) are captured in real-time
4. **Screenshot Capture**: Each action captures a full-page screenshot and element snapshot
5. **Event Queuing**: Events flow through a thread-safe queue (`SimpleQueue`)

### Event Structure

Each recorded event contains:

```json
{
  "action": {
    "action": "click",
    "button": "left",
    "count": 1
  },
  "target": {
    "tag": "button",
    "inner_text": "Submit Form",
    "classes": ["btn", "btn-primary"],
    "attributes": {
      "type": "submit",
      "id": "form-submit"
    }
  },
  "selectors": {
    "css": "button#form-submit",
    "xpath": "//button[@id='form-submit']",
    "text_xpath": "//button[text()='Submit Form']"
  },
  "semantic": {
    "normalized_text": "submit form",
    "input_type": null,
    "role": "button"
  },
  "context": {
    "parent": "<form class='login-form'>",
    "siblings": ["Password input", "Email input"],
    "form_context": "User login form"
  },
  "page": {
    "url": "https://example.com/login",
    "title": "Login - Example App"
  },
  "visual": {
    "full_screenshot": "sessions/xxx/1_full.jpg",
    "element_snapshot": "sessions/xxx/1_element.jpg",
    "bbox": { "x": 100, "y": 200, "w": 80, "h": 40 },
    "viewport": "1920x1080"
  },
  "state_change": {
    "before": "Form has validation errors",
    "after": "Validation passed, form submitted"
  },
  "timing": {
    "wait_before_ms": 0,
    "action_timeout_ms": 5000,
    "wait_after_ms": 500
  }
}
```

### Key Components

**`app/recorder/session.py`** — Main recording coordinator
- Manages Playwright browser lifecycle
- Threads: Driver thread (event pump) + main async thread
- Thread-safe event queue: `_pending_payloads` (SimpleQueue)
- Streaming event materialization (events.jsonl)

**`app/recorder/bridge.js`** — In-page JavaScript bridge
- Injected via `expose_binding` at page load
- Captures DOM events: click, input, change, navigation
- Extracts element selectors, attributes, text content
- Forwards payloads to Python via `window.__skillReport()`

**`app/recorder/visual.py`** — Screenshot & element capture
- Full page screenshot (JPEG)
- Element bounding box snapshot
- Saves relative to session directory

---

## Pipeline Processing

### Pipeline Flow

```
Raw Events → Validation → Cleaning → Deduplication → Semantic Enrichment → Scroll Annotation
```

### Stage 1: Validation

**File**: `app/pipeline/run.py` - `run_pipeline()`

```python
# Convert raw dict to validated RecordedEvent model
validated = [RecordedEvent.model_validate(row).model_dump(mode='json') for row in events]
```

**What it does**:
- Ensures each event conforms to `RecordedEvent` schema
- Raises validation error if missing required fields
- Normalizes types (string → int, etc.)

### Stage 2: Cleaning

**File**: `app/pipeline/run.py` - `_clean_one()`

Cleaning normalizes data for downstream processing:

**Target Cleaning**:
- Collapse whitespace in `inner_text` (max 2000 chars)
- Normalize CSS class names (remove invalid tokens)
- Remove duplicate classes
- Sort classes alphabetically

**Selector Cleaning**:
- Canonicalize CSS selectors
- Verify XPath validity
- Score selector robustness

**Semantic Cleaning**:
- Normalize text to lowercase
- Collapse whitespace
- Limit to 500 chars

**Context Cleaning**:
- Deduplicate sibling text
- Collapse parent HTML
- Preserve form context

### Stage 3: Deduplication

**File**: `app/pipeline/dedupe.py`

**Why**: Consecutive identical scroll events create noise
- Merges scroll events with identical `scroll_position`
- Preserves first screenshot
- Removes duplicate payloads

### Stage 4: Semantic Enrichment

**File**: `app/pipeline/run.py` - `_semantic_enrich_one()`

Calls LLM to extract semantic meaning:

```python
enriched = enrich_semantic(
    SemanticLLMInput(
        raw_text="Submit Form",
        element_type="button",
        context="Login - Example App"
    )
)
# Result: { intent: "submit_form", normalized_text: "submit form" }
```

**LLM Input**:
- Raw element text
- Element type/role
- Page context

**LLM Output**:
- Semantic intent (normalized action meaning)
- Corrected normalized text
- Input type detection (email, password, etc.)

### Stage 5: Scroll Annotation

**File**: `app/pipeline/run.py` - `_annotate_scroll_amounts()`

Calculates scroll delta between consecutive events:

```python
if action == "scroll":
    extras["scroll_amount"] = current_y - last_y
```

### Final Enrichment

**File**: `app/pipeline/enrich.py` - `enrich_event()`

Adds metadata:
- Pipeline version
- Event ordinal (sequence number)
- Computed checksums
- Confidence scores

---

## LLM Enrichment

### When LLM is Called

1. **Semantic Enrichment**: During pipeline processing
2. **Intent Validation**: Before skill compilation
3. **Recovery**: If action execution fails

### LLM Components

**`app/llm/semantic_llm.py`** — Semantic meaning extraction

```python
def enrich_semantic(input: SemanticLLMInput) -> SemanticOutput:
    """Extract semantic intent from element text + context."""
    prompt = f"""
    Element text: {input.raw_text}
    Element type: {input.element_type}
    Page context: {input.context}
    
    Determine the semantic intent of clicking/interacting with this element.
    Return: {{ intent: string, normalized_text: string }}
    """
    response = claude.messages.create(
        model="claude-opus-4-7",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return parse_response(response)
```

**Input to LLM**:
- Element text (e.g., "Submit", "Login", "Save Changes")
- Element type/role (button, input, link, etc.)
- Page title/URL context

**LLM Response**:
```json
{
  "intent": "submit_login_form",
  "normalized_text": "submit login form",
  "confidence": 0.95
}
```

**`app/llm/vision_llm.py`** — Visual reasoning

Used when:
- Need to understand complex UI layouts
- Action failed and visual recovery needed
- Text extraction failed

**Input**:
- Screenshot (full or element)
- Query (e.g., "Is the submit button visible?")

**`app/llm/recovery_llm.py`** — Failure recovery

When action execution fails:
- Analyzes error + current screenshot
- Suggests alternative selectors
- Recommends next step

---

## Human Editing

### Editing Interface (`/frontend`)

The UI allows humans to refine captured workflows:

### Editable Fields per Event

**1. Action**
- Modify action type (click → type, scroll → navigate)
- Change action parameters (button, count, text)

**2. Target**
- Edit element text
- Update semantic intent
- Modify selector strategy

**3. Selectors**
- Switch to most reliable selector (CSS/XPath/text-based)
- Customize selector robustness scoring
- Add anchor elements for fragile UI

**4. Wait Timing**
- `wait_before_ms`: Delay before action
- `action_timeout_ms`: Max time to find element
- `wait_after_ms`: Delay after action (for async state changes)

**5. Validation Rules**
- Add success criteria (expected text, element presence)
- Define failure conditions
- Add recovery steps

**6. Screenshots**
- View full page snapshot
- See element bounding box
- Annotate with notes

### Editing Flow

```
1. Load recorded events from session
2. Display event with visual preview + editable fields
3. User modifies action, selectors, timing, validation
4. System validates changes against screenshot
5. Save to workflow (events stored, selectors re-scored)
6. Preview compiled skill with updated logic
```

### What Gets Validated During Editing

- Selector validity (CSS/XPath syntax)
- Action parameters (required fields)
- Timing values (non-negative)
- Intent semantic consistency
- State change expectations

---

## Workflow Compilation

### Compilation Pipeline

```
Edited Events → Action Extraction → Selector Scoring → Intent Validation → Action Semantics → Compiled Skill
```

### Stage 1: Action Extraction

**File**: `app/compiler/action_semantics.py`

Converts event data into executable Actions:

```python
class Action:
    type: Literal["click", "type", "navigate", "scroll", "wait", "extract"]
    selector: str  # Best selector
    selectors: List[str]  # Fallback selectors
    text?: str  # For type action
    wait_before_ms?: int
    wait_after_ms?: int
    timeout_ms?: int
```

### Stage 2: Selector Scoring

**File**: `app/compiler/selector_score.py`

Ranks selectors by robustness:

```python
def score_selector(selector: str, context: dict) -> float:
    """Score 0.0-1.0 based on stability."""
    score = 1.0
    
    # CSS more stable than XPath
    if selector.startswith("//"):
        score -= 0.1  # XPath penalty
    
    # ID selectors more stable than class
    if "#" in selector:
        score += 0.2
    elif "." in selector:
        score -= 0.1
    
    # Complex selectors are fragile
    score -= len([p for p in selector.split() if p.startswith("[")]) * 0.05
    
    return max(0.0, min(1.0, score))
```

### Stage 3: Intent Validation

**File**: `app/compiler/intent_validation_rules.py`

Validates semantic consistency:

```
Rule 1: Click action on button-like element must have submit/select intent
Rule 2: Text input (type action) requires input element
Rule 3: Navigation action must change URL
Rule 4: All selectors must find exactly 1 element
```

### Stage 4: Dependency Resolution

**File**: `app/compiler/dependencies.py`

Analyzes action relationships:

```
Dependency: Action B depends on Action A if:
- Action B's selector includes text from Action A's result
- Action B's timing assumes Action A completed
- Action A's state_change required for Action B's precondition
```

### Compiled Skill Output

```json
{
  "name": "login_workflow",
  "description": "Complete user login workflow",
  "steps": [
    {
      "id": "step_1",
      "action": "navigate",
      "url": "https://example.com/login",
      "wait_after_ms": 2000
    },
    {
      "id": "step_2",
      "action": "type",
      "selector": "input[name='email']",
      "selectors_fallback": [
        "input#email-field",
        "//input[@type='email']"
      ],
      "text": "${email}",
      "selector_confidence": 0.95,
      "wait_after_ms": 500
    },
    {
      "id": "step_3",
      "action": "type",
      "selector": "input[name='password']",
      "text": "${password}",
      "wait_after_ms": 500
    },
    {
      "id": "step_4",
      "action": "click",
      "selector": "button[type='submit']",
      "wait_after_ms": 2000,
      "validation": {
        "success_criteria": "URL contains '/dashboard'",
        "timeout_ms": 10000
      }
    }
  ],
  "parameters": [
    {
      "name": "email",
      "type": "string",
      "required": true,
      "placeholder": "user@example.com"
    },
    {
      "name": "password",
      "type": "string",
      "required": true,
      "sensitive": true
    }
  ],
  "validation_flow": [
    {
      "after_step": "step_4",
      "checks": [
        { "type": "url_contains", "value": "/dashboard" },
        { "type": "element_visible", "selector": "[data-testid='user-menu']" }
      ]
    }
  ]
}
```

---

## Skill Package Generation

### Package Structure

```
skill_package/
├── README.md                 # Human-readable skill descriptions
├── skills.json              # Compiled skill definitions
├── execute.py               # Universal Playwright execution engine
├── recovery.py              # Self-healing recovery logic
├── vision_recovery.py       # Vision-based element detection
└── pyproject.toml           # Python package metadata
```

### README.md Template

Generated README includes:

```markdown
# Render.com Plugin

Complete automation for deploying services on Render.com.

## Available Skills

### 1. Login to Render
Authenticate with Render account
- **Parameters**: email, password
- **Success Criteria**: Dashboard visible with user menu

### 2. Create New Service
Create new service from GitHub repository
- **Parameters**: repo_url, service_name, branch
- **Success Criteria**: Service created and shown in dashboard

### 3. Deploy Service
Deploy service using current code
- **Success Criteria**: Deployment logs visible, status = "live"

### 4. Monitor Deployment
Check deployment status and logs
- **Output**: {status: "live" | "building" | "failed", logs: []}
```

### Execution Engine (`execute.py`)

```python
class SkillExecutor:
    async def execute_skill(
        self, 
        skill_name: str, 
        parameters: dict, 
        headless: bool = False
    ) -> ExecutionResult:
        """
        1. Load skill definition from skills.json
        2. Prepare Playwright browser
        3. Execute each step sequentially
        4. Validate after each step
        5. On failure, attempt LLM recovery
        6. On LLM recovery fail, attempt vision recovery
        7. Return final result
        """
        browser = await self.launch_browser(headless)
        try:
            for step in skill.steps:
                result = await self.execute_step(step, parameters)
                if not result.success:
                    result = await self.recover_from_failure(
                        step, 
                        browser.page,
                        result.error
                    )
                if still not success:
                    return ExecutionResult(success=False, error=...)
            return ExecutionResult(success=True, output={...})
        finally:
            await browser.close()
```

### Recovery Layers (Tiered System)

The skill package includes a **4-layer tiered recovery mechanism** activated when action execution fails. Each layer adds sophisticated fallback strategies.

**Layer 1: Selector Context** (Instant)
```json
{
  "selector_context": {
    "primary": "button#submit",
    "alternatives": ["button.btn-primary", "button[type='submit']"]
  }
}
```
- **Primary selector**: Best CSS selector found during compilation
- **Alternatives**: Fallback selectors to try sequentially
- **Timeout**: None (instant CSS queries)
- **Success rate**: 60-70% for simple selector changes

**Layer 2: Text Anchors** (Instant)
```json
{
  "anchors": [
    {"text": "Submit", "priority": 1.0},
    {"text": "Send", "priority": 0.8},
    {"text": "Confirm", "priority": 0.6}
  ]
}
```
- **Text-based anchors**: Visual reference points from original recording
- **Priority scoring**: Semantic relevance to original intent
- **Method**: Text node search + fuzzy matching
- **Timeout**: None (instant DOM search)
- **Success rate**: 50-60% for UI text changes

**Layer 3: Text Fallback Variants** (Instant)
```json
{
  "fallback": {
    "text_variants": ["submit", "send", "confirm"],
    "role": "button"
  }
}
```
- **Text variants**: Normalized text alternatives (lowercase, singular/plural)
- **Role**: Element type hints (button, input, link, etc.)
- **Method**: Semantic text expansion + role-based querying
- **Timeout**: None (instant element search)
- **Success rate**: 40-50% for minor text variations

**Layer 4: Visual Recovery** (Vision LLM - 120 sec timeout)
```json
{
  "visual_ref": "Image_3.jpg",
  "visual_metadata": {
    "step_id": 3,
    "source": "stored_step_visual",
    "available": true
  }
}
```
- **Visual asset**: Screenshot from original recording step
- **Vision LLM analysis**: Identify interactive elements on current screenshot
- **Intent matching**: Score candidates against recorded intent
- **Timeout**: 120 seconds (expensive multimodal inference)
- **Success rate**: 75-85% for significant UI changes

### Retry Strategy

**Element Actions** (click, fill, select, focus):
- Total attempts: 2
- Flow: Try L1 → L2 → L3 → Fallthrough L4 if enabled

**Navigate/Check Actions**:
- Total attempts: 3
- Flow: Try primary → Try alternatives → Visual recovery

---

## Execution with Recovery Flow

```
┌─────────────────────────────────────┐
│  Execute Step with Primary Selector │
│  (from execution.json)              │
└──────────────┬──────────────────────┘
               │ Success? → Next step
               │ Failure? ↓
┌─────────────────────────────────────┐
│  Layer 1: Try Alternative Selectors │
│  (selector_context.alternatives)    │
└──────────────┬──────────────────────┘
               │ Success? → Next step
               │ Failure? ↓
┌─────────────────────────────────────┐
│  Layer 2: Text Anchor Search        │
│  (anchors with priority scoring)    │
└──────────────┬──────────────────────┘
               │ Success? → Next step
               │ Failure? ↓
┌─────────────────────────────────────┐
│  Layer 3: Text Variant Fallback     │
│  (normalized text alternatives)     │
└──────────────┬──────────────────────┘
               │ Success? → Next step
               │ Failure? ↓
┌─────────────────────────────────────┐
│  Layer 4: Vision LLM Recovery       │
│  (screenshot + vision model)        │
│  (120 sec timeout)                  │
└──────────────┬──────────────────────┘
               │ Success? → Next step
               │ Failure? ↓
        ⚠️  WORKFLOW FAILS
```

---

## Complete Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER RECORDS WORKFLOW                         │
│              (Playwright Browser + JavaScript Bridge)            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │   RAW EVENTS (events.jsonl)            │
         │  - Action (click, type, navigate)     │
         │  - Target (tag, classes, text)        │
         │  - Selectors (CSS, XPath, text)       │
         │  - Screenshots (full + element)       │
         │  - Page context (URL, title)          │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │     PIPELINE PROCESSING                │
         │  1. Validation (schema check)         │
         │  2. Cleaning (normalize text/selectors)│
         │  3. Deduplication (merge scrolls)     │
         │  4. Semantic Enrichment (LLM)         │
         │  5. Scroll Annotation (delta calc)    │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │  LLM ENRICHMENT RESPONSE               │
         │  - Semantic intent (e.g., submit_form)│
         │  - Normalized text                    │
         │  - Confidence score                   │
         │  - Input type (email, password, etc)  │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │   HUMAN EDITING UI (/frontend)         │
         │  - Review each event                  │
         │  - Modify action/selectors/timing     │
         │  - Validate against screenshot        │
         │  - Save workflow                      │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │    WORKFLOW COMPILATION                │
         │  1. Action extraction                 │
         │  2. Selector scoring                  │
         │  3. Intent validation                 │
         │  4. Dependency resolution             │
         │  5. Validation rule generation        │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │   COMPILED SKILL (JSON)                │
         │  - Executable steps                   │
         │  - Parameter definitions              │
         │  - Validation rules                   │
         │  - Fallback selectors                 │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │   SKILL PACKAGE GENERATION             │
         │  - README.md (skill descriptions)     │
         │  - skills.json (all compiled skills)  │
         │  - execute.py (execution engine)      │
         │  - recovery.py (LLM recovery layer)   │
         │  - vision_recovery.py (vision layer)  │
         └────────────────────────────────────────┘
                              ↓
         ┌────────────────────────────────────────┐
         │   EXECUTABLE SKILL PACKAGE             │
         │  Ready to:                            │
         │  - Execute via Claude agent            │
         │  - Self-heal on failure                │
         │  - Combine with other skills          │
         │  - Publish to GitHub                  │
         └────────────────────────────────────────┘
```

---

## Configuration & Timeouts

### Key Environment Variables

```bash
# LLM Configuration
SKILL_LLM_API_KEY=sk-ant-...           # Claude API key
SKILL_LLM_VISION_MODEL=claude-opus-4.7  # Vision model
SKILL_LLM_TIMEOUT_MS=2000              # Text LLM timeout
SKILL_LLM_VISION_TIMEOUT_MS=120000     # Vision LLM timeout (2 min)

# Recording
SKILL_SCREENSHOT_JPEG_QUALITY=80       # Screenshot compression

# Storage
SKILL_DATA_DIR=/data                   # Event storage directory
SKILL_DATABASE_URL=postgres://...      # Event history DB
SKILL_BLOB_READ_WRITE_TOKEN=...        # Screenshot storage
```

### Timing Defaults

```python
# app/policy/timing.py
TIMING_POLICY = {
    "click": {"wait_before": 0, "timeout": 5000, "wait_after": 500},
    "type": {"wait_before": 0, "timeout": 5000, "wait_after": 300},
    "navigate": {"wait_before": 0, "timeout": 10000, "wait_after": 2000},
    "scroll": {"wait_before": 0, "timeout": 3000, "wait_after": 500},
}
```

---

## Error Handling & Recovery

### Recording Phase Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| `bridge_not_loaded_on_start_page` | Script injection failed | Retry page load |
| `binding_not_available_on_start_page` | `expose_binding` failed | Check browser support |
| `pump_error: ...` | Event pump crashed | Log + continue |

### Pipeline Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| `ValidationError` | Missing required field | Skip event + log |
| `LLM timeout` | Vision model slow | Use fallback selector |
| `Invalid selector` | Malformed CSS/XPath | Regenerate from element |

### Compilation Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| `Selector ambiguous` | Multiple matches | Score + pick best |
| `Intent mismatch` | Semantic inconsistent | Flag for human review |
| `Circular dependency` | Actions depend on each other | Topological sort |

### Execution Errors & Tiered Recovery

**Example Scenario**: UI changed, "Submit" button moved to different location

```
Attempt 1 - Primary Selector (L1):
  ❌ Fails: button#submit → Element not found
  Recovery path: Continue to L1 alternatives

Attempt 1 - L1 Alternatives:
  ❌ Fails: button.btn-primary → Multiple matches (ambiguous)
  Recovery path: Continue to L2

Attempt 1 - L2 Anchors:
  ✅ Success: Found "Submit" text with priority=1.0
  Result: Executes action ✓
```

**Harder Scenario**: UI completely redesigned, text changed to icon-only button

```
Attempt 1 - Primary & L1 Alternatives:
  ❌ All fail: No matching selectors found

Attempt 1 - L2 Anchors:
  ❌ Fails: "Submit" text no longer exists

Attempt 1 - L3 Text Variants:
  ❌ Fails: "send", "confirm" also missing

Attempt 1 - L4 Vision Recovery:
  🧠 Vision LLM analyzes screenshot
  🧠 Detects all buttons on page
  🧠 Scores candidates against original intent (submit_form)
  ✅ Finds button matching recorded intent
  Result: Executes action ✓
```

**Critical Failure**: All layers exhausted

```
All layers fail → Workflow stops
Error reported: "Could not locate element after 4 recovery attempts"
Human intervention: User reviews screenshot, may need to re-record
```

---

## Best Practices

### Recording
- ✅ Record slowly, pause between actions (let state settle)
- ✅ Use real credentials on test accounts
- ✅ Include success scenarios only
- ❌ Don't record error handling (handle separately)
- ❌ Don't record multiple workflows in one session

### Editing
- ✅ Review LLM intent suggestions
- ✅ Add validation rules (check for success)
- ✅ Adjust timing if pages are slow
- ✅ Use IDs/data attributes when possible
- ❌ Don't rely solely on text content (can change)
- ❌ Don't create overly complex conditional logic

### Packaging
- ✅ Write clear README with parameter descriptions
- ✅ Include examples of skill combinations
- ✅ Test with different browsers/viewport sizes
- ✅ Document failure modes + recovery steps
- ❌ Don't hardcode credentials
- ❌ Don't assume specific UI framework versions

