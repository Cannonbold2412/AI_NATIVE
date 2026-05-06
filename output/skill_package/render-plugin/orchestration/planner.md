# Planner Guide

## Your Job

Convert a user request into a JSON plan that `../execution/executor.js` can execute.

## Steps

1. Read `../render.json` to see available skills
2. Identify which skill(s) the user needs (one or more, in order)
3. For each chosen skill, read `../skills/<skill-name>/input.json` for required inputs
4. Ask the user for any missing inputs - ask once, not repeatedly
5. Return ONLY the JSON plan matching `schema.json`, no explanations

## Rules

* ONLY use skills listed in `../render.json`
* DO NOT invent or guess skill names
* DO NOT output anything outside the JSON plan
* Recovery is automatic - do not plan for failure explicitly
