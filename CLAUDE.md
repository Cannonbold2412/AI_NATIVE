# CLAUDE.md

This file provides guidance to Claude Code (`claude.ai/code`) when working with this repository.

---

## 1. Think Before Coding

**Don’t assume. Don’t hide confusion. Surface tradeoffs.**

Before implementing:

- Explicitly state assumptions. If unsure, ask.
- If multiple interpretations exist, present them — don’t silently choose one.
- If a simpler approach exists, call it out.
- If something is unclear, stop and ask.

---

## 2. Simplicity First

**Write the minimum code needed. Nothing speculative.**

- No extra features beyond the requirement  
- No abstractions for single-use code  
- No unnecessary configurability  
- No handling for impossible scenarios  

> If you wrote 200 lines but it could be 50 → rewrite it.

Ask yourself:  
**“Would a senior engineer say this is overcomplicated?”**

---

## 3. Surgical Changes

**Touch only what’s necessary.**

When editing:

- Don’t modify unrelated code
- Don’t refactor unless asked
- Match existing style
- Mention issues, don’t fix them unless required

If your changes create unused code:
- Remove only what *you* introduced

> Every changed line must trace directly to the task.

---

## 4. Goal-Driven Execution

**Define success → implement → verify**

Example:

```
1. Add feature → verify via test
2. Fix bug → reproduce → fix → verify
3. Refactor → ensure no behavior change
```

---

## Token & File Constraints
- DO NOT read files larger than 25KB completely into context.
- When inspecting large files, logs, or databases, ALWAYS use `offset` and `limit` parameters to look at relevant chunks.
- Prioritize using terminal utilities (like `grep`, `awk`, or `tail`) to locate lines before attempting to read a file chunk.

---


# Conxa: AI-Driven Workflow Automation Platform

## Overview

Conxa is a **marketplace for AI-native automation plugins**, built from real workflow recordings and executed by AI agents.

---

## What We’re Building

A system where:

1. Users record real workflows  
2. Convert them into structured skills  
3. Package them into reusable plugins  
4. Let AI dynamically execute them  

---

## Core Architecture

### 1. Workflow Recorder → Structured Editor

- Record real workflows  
- Convert each into **one skill (`SKILL.md`)**  
- Human refines into production-ready logic  

---

### 2. Multi-Skill Aggregation

Multiple recordings → multiple skills

**Example (Render plugin):**
- Login  
- Create service  
- Deploy from GitHub  
- Monitor deployment  

---

### 3. Plugin Packager

- Combine skills + execution engine  
- Output: **One plugin capable of multiple tasks**

---

### 4. Execution Flow

1. Agent reads `CLAUDE.md`  
2. Plans required skills  
3. Requests inputs  
4. Executes using automation engine  

---

### 5. Deterministic Execution with Self-Healing Fallbacks

Runtime tries selectors in order; only Claude LLM fires on Tier 3+ fallback:

- **Tier 1 (compiled)**: Use `step.compiled_selectors` generated at compile time from recorded DOM. Fast, reliable, no LLM cost.
- **Tier 2 (a11y)**: Query a11y tree by role + name. Works when DOM shifts slightly. No LLM.
- **Tier 3 (LLM recovery)**: Claude LLM locates element on current DOM given semantic description. Expensive, used only when Tiers 1-2 fail.
- **Tier 4 (vision)**: Claude vision model locates by screenshot. Last resort; used when text-based recovery fails.
- **Escalation**: All 4 tiers fail → human review queue. No silent fallback or guessing.

Each recording session produces a DOM snapshot (SHA256 hash). Selectors are cached by (dom_hash, bbox, model). When the page layout changes, the next tier activates automatically.

---

## Output: Plugin Marketplace

### For Companies

- Record workflows  
- Convert into skills  
- Package into plugins  
- Publish on GitHub  

### We Provide

- Plugin generation  
- Execution engine  
- Version control

### For Users

- Download plugins  
- AI reads capabilities  
- Plans workflows  
- Executes autonomously relaibely  

---

## Why This Is Different

- ❌ Not RPA → no rigid scripts  
- ❌ Not templates → real workflows  
- ❌ Not brittle → self-healing system  

- ✅ AI-native planning  
- ✅ Dynamic execution  
- ✅ Scalable architecture  

---

## Vision

> Turn every real workflow into an executable AI capability.

---
