# Fix: Plugin Detail Page Crash / Chromium Recording Unreachable

## Symptom

Opening the Conxa Build Studio and clicking any plugin in the sidebar showed a red error banner in the main content area:

```
get_plugin
```

The plugin detail page never loaded — no tabs, no workflow list, no "Record new workflow" button. Because the detail page is the gateway to launching the Chromium-based recorder, recording a new workflow was unreachable from the UI.

## Root Cause

`PluginDetail.tsx` fires an IPC command as soon as a plugin is selected:

```typescript
cmd<{ plugin: PluginInfo }>("get_plugin", { plugin_id: pluginId })
```

The Python backend (`backend.py`) dispatches commands by looking up a method named `cmd_{type}`. There was no `cmd_get_plugin` method. The dispatch fallback returned:

```python
{"type": "error", "code": "unknown_command", "message": "get_plugin"}
```

The renderer caught this, extracted `e.message` ("get_plugin"), and rendered it as the error banner. The `get_plugin` function already existed in `conxa_core/storage/plugin_store.py` — it was simply never wired up as an IPC handler.

## Fix

Added `cmd_get_plugin` to `conxa-builder/python/backend.py` immediately after `cmd_list_plugins`:

```python
def cmd_get_plugin(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
    from conxa_core.storage.plugin_store import get_plugin
    from conxa_core.storage.json_store import read_skill

    plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
    data = plugin.model_dump(mode="json")
    for wf_data, wf in zip(data["workflows"], plugin.workflows):
        step_count = 0
        if wf.skill_id:
            try:
                skill = read_skill(wf.skill_id)
                if skill:
                    step_count = len((skill.get("skills") or [{}])[0].get("steps") or [])
            except Exception:
                pass
        wf_data["step_count"] = step_count
    return {"plugin": data}
```

The handler:
- Validates `plugin_id` via the shared `_safe_id` helper
- Loads the full plugin from storage
- Enriches each workflow with `step_count` (read from the compiled skill file when available, 0 otherwise) to match the `PluginInfo` TypeScript interface
- Returns `{"plugin": <full plugin dump>}`

No frontend changes were needed. No data model changes were needed.

## Files Changed

| File | Change |
|------|--------|
| `conxa-builder/python/backend.py` | Added `cmd_get_plugin` method |

## What Was Not a Bug

All six plugins showing the name "Render" with amber warning triangles is correct behavior:
- The names are stored data — the user created these test plugins named "Render"
- The amber triangle (▲) is the `StatusDot` "unpublished" indicator, shown when a plugin's status is `needs_auth` or any state that is not `ready` or `error`. This is expected for newly created plugins that haven't had auth recorded yet.
