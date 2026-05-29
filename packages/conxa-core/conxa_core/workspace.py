"""Workspace identity constant shared by the storage layer and the SaaS layer.

The local/offline workspace id is referenced both by the plugin store (which
stamps every locally created plugin) and by the cloud SaaS metadata. Keeping it
here lets the storage foundation stay independent of the cloud-only SaaS module.
"""

from __future__ import annotations

LOCAL_WORKSPACE_ID = "wrk_local"
