# ⚡ Conxa Quick Reference Guide

## 🎯 One-Sentence Summary
**Conxa records real user workflows → cleans & enriches events via LLM → humans refine → compiles to executable skills → self-heals when UI changes.**

---

## 📊 The 7-Stage Pipeline

```
┌─────────────┬──────────────┬────────────┬──────────────┬────────────┬──────────────┬─────────────┐
│ 📹 RECORD   │ ⚙️ PIPELINE  │ 🧠 LLM     │ ✏️ EDIT      │ 🔧 COMPILE │ 📦 PACKAGE   │ ⚡ EXECUTE  │
├─────────────┼──────────────┼────────────┼──────────────┼────────────┼──────────────┼─────────────┤
│ • Browser   │ • Validate   │ • Intent   │ • Review     │ • Actions  │ • README     │ • Browser   │
│   capture   │ • Clean      │   extract  │ • Refine     │ • Score    │ • Execution  │ • Execute   │
│ • DOM       │ • Dedup      │ • Normalize│ • Add rules  │ • Validate │ • Recovery   │ • Validate  │
│   analysis  │ • Annotate   │ • Tags     │ • Timing     │ • Package  │ • Vision     │ • Recover   │
└─────────────┴──────────────┴────────────┴──────────────┴────────────┴──────────────┴─────────────┘
```

---

## 🔑 Key Concepts

| Concept | Definition | Example |
|---------|-----------|---------|
| **Event** | Raw captured interaction | User clicks button, types text |
| **Action** | Compiled executable step | Click selector "button#submit" |
| **Selector** | DOM element locator | CSS: `button#submit`, XPath: `//button` |
| **Intent** | Semantic meaning of action | `submit_login_form`, `fill_email_field` |
| **Skill** | Sequence of related actions | Login workflow (navigate → type → type → click) |
| **Parameter** | User-provided input | `${email}`, `${password}` |
| **Validation** | Success criteria | URL contains "/dashboard" |

---

## 📝 Event Structure

### Raw Event (Post-Recording)
```json
{
  "action": {"action": "click", "button": "left"},
  "target": {"tag": "button", "inner_text": "Submit", "classes": ["btn"]},
  "selectors": {"css": "button.btn", "xpath": "//button"},
  "semantic": {"normalized_text": "submit", "llm_intent": null},
  "visual": {"full_screenshot": "path/to/image.jpg"},
  "page": {"url": "https://...", "title": "Page Title"},
  "timing": {"wait_before_ms": 0, "action_timeout_ms": 5000}
}
```

### After Enrichment
```json
{
  "semantic": {
    "normalized_text": "submit",
    "llm_intent": "submit_login_form",        // ← FROM LLM
    "confidence": 0.98,                       // ← LLM CONFIDENCE
    "role": "button"
  }
}
```

### Compiled Action (Post-Compilation)
```json
{
  "id": "step_1",
  "action": "click",
  "selector": "button#submit",               // ← BEST SELECTOR
  "selector_confidence": 0.95,               // ← STABILITY SCORE
  "selectors_fallback": ["button.btn", "//button"],  // ← BACKUPS
  "validation": {
    "success_criteria": [
      {"type": "url_contains", "value": "/dashboard"}
    ]
  },
  "wait_after_ms": 2000
}
```

---

## 🎯 LLM Enrichment

### When LLM is Called
1. **Pipeline**: Extract semantic intent from raw events
2. **Validation**: Verify semantic consistency during compilation
3. **Recovery**: Fix failed actions (if selector doesn't work)

### LLM Input
```
Element text: "Submit Login"
Element type: "button"
Page context: "User authentication form"
```

### LLM Output
```
{
  "intent": "submit_login_form",
  "normalized_text": "submit login",
  "confidence": 0.95
}
```

### Timeouts
- **Text LLM**: 2 seconds (fast semantic analysis)
- **Vision LLM**: 120 seconds (expensive image analysis)

---

## 📊 Selector Scoring

Higher = More Stable ⬆️

| Selector Type | Score | Example |
|---------------|-------|---------|
| ID-based | 0.95 | `button#submit-btn` |
| Class-based | 0.75 | `button.btn.btn-primary` |
| Attribute | 0.70 | `button[type='submit']` |
| XPath | 0.65 | `//button[@id='submit']` |
| Text-based | 0.45 | `//button[text()='Submit']` |

**Strategy**: Use highest-scoring selector, keep others as fallbacks.

---

## 🔄 Recovery Layers (4-Tier Tiered System)

**L1: Selector Context** (Instant)
- Primary selector + alternatives (CSS, XPath)
- Success rate: 60-70%
- When: Always first attempt

**L2: Text Anchors** (Instant)
- Text-based reference points with priority scoring
- Success rate: 50-60%
- When: If L1 fails

**L3: Text Fallback Variants** (Instant)
- Normalized text alternatives + element role
- Success rate: 40-50%
- When: If L1 & L2 fail

**L4: Vision Recovery** (⏱️ 120 sec timeout)
- Screenshot analysis with vision LLM
- Detect interactive elements on screen
- Score candidates against original intent
- Success rate: 75-85%
- When: If L1-L3 all fail

**Combined Success Rate**: ~95% (Layer 1-3 instant, Layer 4 vision fallback)

### Retry Strategy
- **Element actions** (click, fill): 2 total attempts
- **Navigate/Check**: 3 total attempts
- **Flow**: L1 → L2 → L3 → (if enabled) L4 → Fail

---

## ✏️ Editing Workflow

**What humans can edit:**

1. **Action Type** → click → type, navigate, scroll, wait
2. **Selectors** → switch between CSS/XPath/text-based
3. **Timing** → adjust wait_before, wait_after, timeout
4. **Validation** → add success criteria, expected state changes
5. **Intent** → verify/correct LLM-generated semantic intent

**Why editing matters:**
- Selectors based on IDs are more stable than class-based
- Longer waits for slow pages prevent premature actions
- Validation rules catch failures early
- Intent correction improves recovery layer effectiveness

---

## 📦 Skill Package Contents

```
skill_package/
├── README.md               # Human-readable descriptions
├── skills.json             # All compiled skills (JSON)
├── execute.py              # Universal Playwright executor
├── recovery.py             # LLM-based recovery
├── vision_recovery.py      # Vision-based recovery
└── pyproject.toml          # Python package metadata
```

### README.md Template
```markdown
# Plugin Name

## Available Skills

### 1. Skill Name
Description
- Parameters: param1, param2
- Success: URL contains "/dashboard"

### 2. Another Skill
...
```

---

## ⚡ Execution Flow

```
1. Load skill from skills.json
2. For each step:
   a. Find element using best selector
   b. If not found, try fallbacks
   c. Execute action (click, type, navigate, etc.)
   d. Wait for state change
   e. Check validation criteria
   f. If failed → LLM Recovery (Layer 1)
   g. If still failed → Vision Recovery (Layer 2)
   h. If all failed → Mark as failed, continue or abort
3. Return results (success, output, errors)
```

---

## 🧪 Validation Rules

| Rule Type | Purpose | Example |
|-----------|---------|---------|
| `url_contains` | Check URL changed | `"/dashboard"` |
| `element_visible` | Element appeared | `"[data-testid='menu']"` |
| `text_present` | Specific text visible | `"Welcome, John"` |
| `element_hidden` | Element disappeared | `".loading-spinner"` |
| `element_enabled` | Button clickable | `"button:not(:disabled)"` |

---

## ⏱️ Timing Configuration

```json
{
  "wait_before_ms": 0,      // Delay before action
  "action_timeout_ms": 5000, // Max time to find element
  "wait_after_ms": 500      // Delay after action (for async updates)
}
```

**Default Timing by Action Type**:
- **click**: 0ms before, 5000ms timeout, 500ms after
- **type**: 0ms before, 5000ms timeout, 300ms after
- **navigate**: 0ms before, 10000ms timeout, 2000ms after
- **scroll**: 0ms before, 3000ms timeout, 500ms after

---

## 📈 Performance Targets

| Metric | Target |
|--------|--------|
| Event capture | 20-50 events per workflow |
| Pipeline processing | <200ms per event |
| LLM enrichment | <2s per event (text), 30-60s (vision) |
| Compilation | <500ms |
| Execution | 1-5s per step (depends on timing) |
| Recovery success | 85% (combined layers) |

---

## 🔍 Debugging Tips

### Event Capture Issues
- Check `binding_errors` in session status
- Verify bridge.js loaded: `window.__SKILL_BRIDGE_V1__`
- Check binding available: `typeof window.__skillReport === 'function'`

### Selector Not Found
1. Check screenshot (is element visible?)
2. Try fallback selectors
3. Trigger LLM recovery
4. Use vision recovery if available

### LLM Timeout
- Vision model is slow (120 sec timeout)
- Fall back to structured selectors
- Consider simplifying query or splitting into smaller events

### Low Confidence
- Review LLM-extracted intent in editor
- Correct if incorrect
- Re-compile with corrected intent

---

## 🚀 Common Workflows

### Login + Navigate + Fill Form
```
Step 1: navigate("https://app.com/login")     → wait 2000ms
Step 2: type(email_field, "${email}")          → wait 500ms
Step 3: type(password_field, "${password}")    → wait 500ms
Step 4: click(submit_button)                   → wait 2000ms + validate URL
```

### Upload + Wait + Verify
```
Step 1: click(upload_input)                    → wait 500ms
Step 2: type(file_path, "${file_path}")        → wait 1000ms
Step 3: click(upload_button)                   → wait 5000ms (long wait for processing)
Step 4: validate(element_visible, success_msg) → wait 1000ms
```

### Scroll + Search + Click
```
Step 1: scroll(down, 500px)                    → wait 500ms
Step 2: type(search_field, "${query}")         → wait 500ms
Step 3: click(search_button)                   → wait 2000ms (results load)
Step 4: click(first_result)                    → wait 1000ms + validate navigation
```

---

## 🐛 Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Element not found` | Selector doesn't match | Check screenshot, use fallback, trigger recovery |
| `Ambiguous selector` | Multiple elements match | Add specificity (ID, data-test attribute) |
| `Validation failed` | Expected state didn't occur | Increase wait time, check expected state |
| `LLM timeout` | Vision model slow | Use structured selector, skip enrichment |
| `Circular dependency` | Actions depend on each other | Reorder actions, split into separate skills |

---

## 📚 Documentation Map

| Need | Resource |
|------|----------|
| Quick visual overview | `complete-pipeline.svg` |
| Interactive learning | `workflow-visualization.html` |
| Data transformations | `data-flow-guide.html` |
| Detailed reference | `ARCHITECTURE_DEEP_DIVE.md` |
| Specific diagram | `recorder-flow.svg`, `llm-processing.svg`, `compilation-execution.svg` |

---

## 🔗 Key Code Locations

| Component | File | Key Function |
|-----------|------|--------------|
| Recording | `app/recorder/session.py` | `RecordingSession.start()` |
| Pipeline | `app/pipeline/run.py` | `run_pipeline(events)` |
| LLM | `app/llm/semantic_llm.py` | `enrich_semantic(input)` |
| Compilation | `app/compiler/action_semantics.py` | `compile_skill(events)` |
| Execution | `skill_package/execute.py` | `SkillExecutor.execute_skill()` |
| Recovery | `skill_package/recovery.py` | `recover_llm()` |

---

## 💡 Pro Tips

✅ **DO:**
- Record slowly, pause between actions (let state settle)
- Use IDs and data attributes in selectors
- Add validation rules for success criteria
- Test with different browsers/viewport sizes
- Document expected parameters and outputs

❌ **DON'T:**
- Record error handling in separate workflow
- Hardcode credentials (use parameters)
- Rely solely on text content (can change)
- Create overly complex conditional logic
- Skip adding validation rules

---

## 📞 Quick Help

**"How do I...?"**

- **...record a workflow?** → Use the Conxa UI, click "Record", perform actions, click "Stop"
- **...edit recorded events?** → Open workflow in editor, modify selectors/timing/validation, save
- **...compile to skill?** → Click "Compile" button in editor, review results
- **...publish skill?** → Generate package, push to GitHub, register in repository
- **...execute skill?** → Load from registry, call execute_skill() with parameters
- **...handle failures?** → LLM recovery tries automatically, then vision recovery, then fails

---

## Version Info
- **Last Updated**: 2026-05-05
- **Conxa Version**: 1.0
- **Python**: 3.13+
- **Browser**: Chrome/Chromium via Playwright

---

**Print this! Keep it handy! 📋**
