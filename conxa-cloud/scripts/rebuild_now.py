#!/usr/bin/env python
import sys
from conxa_compile.plugin_builder import build_plugin

print("[BUILD] Rebuilding plugin with latest code...")
try:
    result = build_plugin('c759c810-ef66-4eac-a0c6-86323267d6dd', version='0.1.1')
    if isinstance(result, dict):
        print(f"[SUCCESS] Plugin built to: {result.get('output_path', 'unknown')}")
        sys.exit(0)
    else:
        print(f"[ERROR] Unexpected result: {result}")
        sys.exit(1)
except Exception as e:
    print(f"[ERROR] Build failed: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
