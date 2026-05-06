# Render Plugin - Orchestration Guide

## Entry Point

Start from `../render.json` - the machine-readable index of all available skills.

## How to Use

1. Read `../render.json` to see all available skills and their inputs
2. Pick the skill(s) that match the user's request
3. Read `planner.md` for how to sequence skills and gather inputs
4. Return a plan matching `schema.json` so `../execution/executor.js` can run it

## Available Skills

- `delete_database`
- `login_in_render`
