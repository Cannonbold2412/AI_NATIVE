# conxa

CLI for installing and running Conxa automation plugins on top of the
shared `conxa` MCP runtime.

## Install plugins

PowerShell on Windows:

```powershell
npx.cmd -y "@kiran_nandi_123/conxa" install "cannonboldoff-hue/render"
```

Generic shell:

```
npx -y "@kiran_nandi_123/conxa" install <plugin_id>
```

Avoid running downloaded scripts inline with `irm` + `scriptblock`. If you need
the PowerShell installer, download and inspect it first:

```powershell
irm "https://cdn.jsdelivr.net/npm/@kiran_nandi_123/conxa/scripts/install.ps1" -OutFile ".\install-conxa.ps1"
Get-Content ".\install-conxa.ps1"
powershell -ExecutionPolicy Bypass -File ".\install-conxa.ps1" "cannonboldoff-hue/render"
```

Plugin refs accepted:

- `acme/hr-onboarding` — GitHub `owner/repo` (cloned via git)
- `acme/hr-onboarding@v1.0.0` — pinned version (git tag)
- `https://github.com/acme/hr-onboarding` — full git URL
- `./my-plugin` — local directory

The first install bootstraps `~/.conxa/runtime/`, registers the `conxa`
MCP server in `~/.claude/settings.json`, and imports the per-plugin
CLAUDE.md instructions into your global `~/.claude/CLAUDE.md`. After
that, Claude Code discovers every installed plugin through a single MCP
connection — no per-plugin setup.

## Other commands

```
conxa list                     # list installed plugins
conxa search <query>           # search installed + cached + registry plugins
conxa uninstall <slug>         # remove an installed plugin
conxa init                     # explicit runtime bootstrap (auto-runs on install)
conxa registry login <url> <token>
conxa registry logout <url>
```

## Architecture

All installed plugins share one MCP server (`conxa`), one Chromium auth
cache, and one runtime install. Plugins themselves are data-only
packages — recorded workflows compiled into deterministic
`execution.json` + `recovery.json` files, with a 5-layer recovery
cascade implemented inside the runtime.

See https://conxa.ai for the broader platform.
