# Publishing the `conxa` npm package

The source-of-truth for runtime code lives in
`app/storage/plugin_templates/runtime/`. Before every publish, mirror it
into `packages/conxa-cli/lib/`:

```bash
python scripts/sync_conxa_cli.py
```

Then:

```bash
cd packages/conxa-cli
npm version <patch|minor|major>
npm publish --access public
```

Smoke test before publishing:

```bash
# Verify the bin runs from package source
HOME=/tmp/conxa-smoke node bin/conxa.js list

# Verify a local-dir install round-trips
HOME=/tmp/conxa-smoke node bin/conxa.js install /path/to/some/plugin
HOME=/tmp/conxa-smoke node bin/conxa.js search <query>
HOME=/tmp/conxa-smoke node bin/conxa.js uninstall <slug>
```

## What ships

- `bin/conxa.js` — thin shim that delegates to `lib/cli.js::runCli`.
- `lib/` — a copy of `app/storage/plugin_templates/runtime/`:
  - `cli.js`, `server.js`, `run.js`, `browser.js`, `config.js`, `runtime.js`,
    `search.js`
  - `resolver/{installed,cache,git,registry}.js`
  - `package.json` — runtime's own deps (`@modelcontextprotocol/sdk`,
    `playwright`); `conxa init` runs `npm install` against this in
    `~/.conxa/runtime/`.

## What does NOT ship

- Any backend Python code from this repo.
- `app/` template directories.
- Plugin build pipeline.
