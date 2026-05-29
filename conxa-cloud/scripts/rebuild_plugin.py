#!/usr/bin/env python
from conxa_compile.plugin_builder import build_plugin

print("[BUILD] Starting plugin rebuild...")
try:
    result = build_plugin('c759c810-ef66-4eac-a0c6-86323267d6dd', version='0.1.0')
    print("[BUILD] Build completed")
    if isinstance(result, dict):
        print(f"[BUILD] Status: {result.get('message', result.get('status', 'unknown'))}")
        if result.get('output_url'):
            print(f"[BUILD] Output: {result['output_url']}")
except Exception as e:
    print(f"[BUILD] Error: {str(e)}")
    import traceback
    traceback.print_exc()
