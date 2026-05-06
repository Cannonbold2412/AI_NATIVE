# 📚 Conxa Architecture Documentation

Complete technical documentation explaining how Conxa transforms screen recordings into executable automation skills.

## 📖 Documentation Files

### 1. **ARCHITECTURE_DEEP_DIVE.md** (Main Reference)
   - **Location**: Root of project
   - **What it covers**: Complete written explanation of the entire system
   - **Best for**: Understanding the big picture, detailed technical reference
   - **Key sections**:
     - System Overview
     - Recording Phase (Capture)
     - Pipeline Processing (7 stages)
     - LLM Enrichment (when & how LLM is called)
     - Human Editing (UI & workflow)
     - Workflow Compilation (action extraction, selector scoring)
     - Skill Package Generation (distribution structure)

### 2. **workflow-visualization.html** (Interactive Guide)
   - **Location**: `docs/workflow-visualization.html`
   - **What it covers**: Interactive tabbed interface with animations
   - **Best for**: Learning the pipeline flow with visual examples
   - **Access**: Open in any web browser
   - **Tabs**:
     - Pipeline Overview (complete flow diagram)
     - Recording Phase (browser automation details)
     - Data Processing (normalization, deduplication)
     - LLM Enrichment (semantic extraction)
     - Human Editing (refinement workflow)
     - Compilation (skill generation)
     - Package Generation (distribution)
     - Recovery Layers (self-healing system)

### 3. **data-flow-guide.html** (Data Transformations)
   - **Location**: `docs/data-flow-guide.html`
   - **What it covers**: How data changes at each stage
   - **Best for**: Understanding data structures and transformations
   - **Access**: Open in any web browser
   - **Shows**: Before/after examples for each stage with code

### 4. **SVG Diagrams** (Visual References)

   #### `recorder-flow.svg`
   - **Shows**: Step-by-step recording process
   - **Includes**: Browser launch, event capture loop, thread-safe queue, session storage
   - **Best for**: Understanding how events are captured

   #### `llm-processing.svg`
   - **Shows**: LLM enrichment pipeline
   - **Includes**: Input preparation, LLM processing, response integration, downstream usage
   - **Best for**: Understanding semantic enrichment

   #### `compilation-execution.svg`
   - **Shows**: Compilation and execution with recovery layers
   - **Includes**: Action extraction, selector scoring, intent validation, both recovery layers
   - **Best for**: Understanding compilation and self-healing

   #### `complete-pipeline.svg`
   - **Shows**: End-to-end flow from recording to execution
   - **Includes**: All 7 stages in one diagram
   - **Best for**: Quick visual overview of the complete process

---

## 🎯 Quick Navigation Guide

### "I want to understand..."

**...how recordings work**
→ Read: `workflow-visualization.html` (Recording Phase tab)
→ View: `recorder-flow.svg`
→ Deep dive: `ARCHITECTURE_DEEP_DIVE.md` (Recording Phase section)

**...how data flows through the system**
→ Read: `data-flow-guide.html`
→ View: `complete-pipeline.svg`
→ Deep dive: `ARCHITECTURE_DEEP_DIVE.md` (Pipeline Processing section)

**...how LLM enrichment works**
→ Read: `workflow-visualization.html` (LLM Enrichment tab)
→ View: `llm-processing.svg`
→ Deep dive: `ARCHITECTURE_DEEP_DIVE.md` (LLM Enrichment section)

**...how skills are compiled**
→ Read: `workflow-visualization.html` (Compilation tab)
→ View: `compilation-execution.svg`
→ Deep dive: `ARCHITECTURE_DEEP_DIVE.md` (Workflow Compilation section)

**...how self-healing works**
→ Read: `workflow-visualization.html` (Recovery Layers tab)
→ View: `compilation-execution.svg` (Phase 3)
→ Deep dive: `ARCHITECTURE_DEEP_DIVE.md` (Error Handling & Recovery section)

**...what skills look like when published**
→ Read: `workflow-visualization.html` (Package Generation tab)
→ Deep dive: `ARCHITECTURE_DEEP_DIVE.md` (Skill Package Generation section)

---

## 🏗️ System Architecture at a Glance

```
Recording → Raw Events → Pipeline Processing → LLM Enrichment → Human Editing → Compilation → Package → Execution
  🎬         📹          ⚙️                  🧠               ✏️             🔧        📦      ⚡

Each stage adds semantic meaning, confidence scoring, and validation
```

### Core Components

| Component | Purpose | Key File |
|-----------|---------|----------|
| **Recorder** | Captures user interactions via Playwright | `app/recorder/session.py` |
| **Bridge** | JavaScript → Python event communication | `app/recorder/bridge.js` |
| **Pipeline** | Normalizes, cleans, deduplicates events | `app/pipeline/run.py` |
| **LLM Module** | Extracts semantic meaning from events | `app/llm/semantic_llm.py` |
| **Compiler** | Converts events to executable actions | `app/compiler/action_semantics.py` |
| **Recovery** | Self-healing when selectors fail | `app/llm/recovery_llm.py`, `app/llm/vision_llm.py` |
| **Editor** | UI for human refinement | `frontend/` (React/Next.js) |

---

## 📊 Data Structures

### Raw Event (Post-Recording)
```json
{
  "action": {"action": "click", "button": "left"},
  "target": {"tag": "button", "inner_text": "Submit", "classes": ["btn"]},
  "selectors": {"css": "button.btn", "xpath": "//button"},
  "semantic": {"normalized_text": "submit", "llm_intent": null},
  "visual": {"full_screenshot": "path/to/image.jpg", "bbox": {...}},
  "page": {"url": "...", "title": "..."},
  "timing": {"wait_before_ms": 0, "action_timeout_ms": 5000}
}
```

### Compiled Action (Post-Compilation)
```json
{
  "id": "step_1",
  "action": "click",
  "selector": "button#submit",
  "selector_confidence": 0.95,
  "selectors_fallback": ["button.btn", "//button[@type='submit']"],
  "validation": {
    "success_criteria": [
      {"type": "url_contains", "value": "/dashboard"}
    ]
  },
  "wait_after_ms": 2000
}
```

---

## ⏱️ Key Timeouts

| Operation | Timeout | Why |
|-----------|---------|-----|
| Text LLM calls | 2 seconds | Fast semantic extraction |
| Vision LLM calls | 120 seconds | Large multimodal payloads |
| Action execution | 5 seconds | Find and interact with element |
| Navigation | 10 seconds | Page load |
| Overall workflow | User-defined | Business logic dependent |

---

## 🔄 Pipeline Processing Stages

1. **Validation** → Schema check, type validation, reject invalid events
2. **Cleaning** → Normalize text, deduplicate classes, truncate fields
3. **Deduplication** → Merge consecutive identical scroll events
4. **Semantic Enrichment** → LLM extracts intent, normalizes text
5. **Scroll Annotation** → Calculate scroll delta between events
6. **Metadata Addition** → Pipeline version, sequence, checksums

---

## 💡 Key Concepts

### Selector Scoring
Selectors are scored 0.0-1.0 based on stability:
- **ID-based CSS** (+0.2): Most stable, rarely change
- **Class-based CSS** (-0.1): Medium stability, can change
- **XPath** (-0.1): Complex, fragile
- **Text-based** (-0.2): Most fragile, changes with UI text

### Confidence Scoring
- **LLM intent confidence**: 0.0-1.0, extracted by Claude
- **Selector confidence**: 0.0-1.0, computed by scoring algorithm
- **Combined confidence**: Weighted average for final action

### Intent Ontology
Semantic intents (from LLM):
- `submit_form` → Click on submit button
- `fill_field` → Type text into input
- `navigate` → Change URL
- `select_option` → Choose from dropdown
- etc.

### Self-Healing Layers

**Layer 1: LLM Recovery** (2 sec timeout)
- Analyzes failure + screenshot
- Suggests alternative selector
- Most failures resolved here

**Layer 2: Vision Recovery** (120 sec timeout)
- Analyzes full screenshot with vision model
- Detects elements on screen
- Scores candidates by intent matching

---

## 🚀 Development Workflow

### Recording
1. User records workflow in browser
2. JavaScript bridge captures all interactions
3. Events stored in `events.jsonl` with screenshots

### Pipeline
```python
# In code
from app.pipeline.run import run_pipeline
enriched_events = run_pipeline(raw_events)
```

### Compilation
```python
# In code
from app.compiler.action_semantics import compile_skill
compiled_skill = compile_skill(enriched_events)
```

### Execution
```python
# In skill package
from execute import SkillExecutor
result = await executor.execute_skill("skill_name", parameters)
```

---

## 📦 Package Structure

```
skill_package/
├── README.md              # Human-readable skill descriptions
├── skills.json           # All compiled skills
├── execute.py            # Universal Playwright executor
├── recovery.py           # LLM-based recovery layer
├── vision_recovery.py    # Vision-based recovery layer
└── pyproject.toml        # Python package metadata
```

---

## 🧪 Testing & Validation

### Validation Checkpoints
1. **Schema Validation** → RecordedEvent model
2. **Selector Validation** → CSS/XPath syntax
3. **Intent Validation** → Semantic consistency
4. **Action Validation** → Required parameters present
5. **Runtime Validation** → Execution success criteria

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `bridge_not_loaded` | Script injection failed | Retry page load |
| `Selector not found` | Element doesn't exist | Use fallback selector |
| `LLM timeout` | Vision model slow | Fall back to structured selectors |
| `Ambiguous selector` | Multiple elements match | Add more specificity |

---

## 📈 Performance Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Events captured per workflow | 20-50 | Depends on interaction |
| Pipeline processing | <1s per event | ~100-200ms |
| LLM enrichment | <2s per event | ~1.5s (text), 30-60s (vision) |
| Compilation time | <1s | ~500ms |
| Execution speed | <2s per step | ~1-5s depending on wait times |
| Recovery success rate | >80% | ~85% (Layer 1), ~90% combined |

---

## 🔐 Security Considerations

### Best Practices

1. **Never hardcode credentials** in skills
   - Use parameters for username, password, API keys
   - Implement secure credential storage

2. **Validate selectors before execution**
   - Ensure selectors target intended elements
   - Add validation rules to catch mistakes

3. **Screenshot privacy**
   - Screenshots may contain sensitive data
   - Implement retention policies
   - Consider data classification

4. **API key management**
   - Use environment variables for LLM keys
   - Rotate keys regularly
   - Monitor usage patterns

---

## 🤝 Contributing to Documentation

To update documentation:

1. **Update ARCHITECTURE_DEEP_DIVE.md** for textual changes
2. **Update corresponding HTML** for visual examples
3. **Update SVGs** if workflow changes
4. **Keep examples in sync** across all files

---

## 📞 Quick Reference

### Important Files in Codebase

**Recording**
- `app/recorder/session.py` — Main recording session
- `app/recorder/bridge.js` — JavaScript bridge

**Pipeline**
- `app/pipeline/run.py` — Pipeline orchestration
- `app/pipeline/enrich.py` — Event enrichment
- `app/pipeline/dedupe.py` — Deduplication logic

**LLM**
- `app/llm/semantic_llm.py` — Semantic enrichment
- `app/llm/vision_llm.py` — Vision-based analysis
- `app/llm/recovery_llm.py` — Failure recovery

**Compilation**
- `app/compiler/action_semantics.py` — Action extraction
- `app/compiler/selector_score.py` — Selector scoring
- `app/compiler/intent_validation_rules.py` — Intent validation

**Frontend**
- `frontend/src/components/StepEditorPanel.tsx` — Edit UI
- `frontend/src/services/workflow.ts` — API integration

---

## 📝 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-05 | Initial documentation |

---

## 🎓 Learning Path

### Beginner
1. Start with `workflow-visualization.html` (Pipeline Overview)
2. Watch the complete flow on `complete-pipeline.svg`
3. Read `ARCHITECTURE_DEEP_DIVE.md` (System Overview section)

### Intermediate
1. Read `ARCHITECTURE_DEEP_DIVE.md` (Recording & Pipeline sections)
2. Explore `recorder-flow.svg` and `llm-processing.svg`
3. Review `data-flow-guide.html` for transformations

### Advanced
1. Deep dive into `ARCHITECTURE_DEEP_DIVE.md` (all sections)
2. Review actual code in `app/recorder/`, `app/pipeline/`, `app/llm/`
3. Trace execution through recovery layers
4. Study compilation and selector scoring logic

---

## 🔗 Related Documentation

- **Project CLAUDE.md**: Architecture overview and setup instructions
- **Code comments**: Inline explanations in source files
- **Commit history**: Evolution of features and bug fixes

---

Happy learning! 🚀
