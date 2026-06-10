# Private GitHub Repo Migration

## Short Answer

The source repository can be made private, but release artifact downloads must stay public or be served by Conxa Cloud. The current app has unauthenticated clients that fetch runtime and Studio binaries from URLs published in update manifests. Those clients cannot use private GitHub credentials.

The main migration is not a code visibility problem. It is an artifact hosting and deployment-permission problem.

## Current Repo Touchpoints

- Source remote: `https://github.com/Cannonbold2412/AI_NATIVE.git`.
- Release build workflows: `.github/workflows/build-runtime.yml` and `.github/workflows/build-studio.yml`.
- Default release URLs:
  - `.env.example`
  - `conxa-cloud/backend/app/api/updates_routes.py`
- Runtime and Studio artifacts currently default to GitHub Release download URLs:
  - `CONXA_RUNTIME_WIN_URL`
  - `CONXA_KEYTAR_WIN_URL`
  - `CONXA_STUDIO_WIN_URL`
  - `CONXA_RUNTIME_CDN_URL`
- Public consumers of those URLs:
  - Build Studio bootstrap downloads `runtime-win.exe` and `keytar.node` into the local dependency cache.
  - The runtime self-updater fetches `/api/v1/updates/runtime-manifest` and downloads `runtime.exe.next` plus `keytar.node.next`.
  - The Cloud frontend fetches `/api/v1/updates/studio-manifest` to show the Build Studio installer download link.

## Required Changes Before Making The Repo Private

1. Reauthorize Render GitHub access.
   - Confirm the Render GitHub App has access to the now-private repo.
   - Confirm the `conxa-api` service still points at the intended branch/root directory.
   - If deploys stop, update the Git credentials in the Render service settings.

2. Reauthorize Vercel GitHub access.
   - Confirm the Vercel GitHub integration can access the private repo.
   - For private org repos, ensure commit authors also have access to the Vercel project/team, otherwise deployments can be blocked.

3. Check GitHub Actions billing and storage.
   - Private repositories use the account or organization Actions minutes and artifact/cache storage quota.
   - The Windows workflows are the important ones here because runtime and Studio builds run on `windows-latest`.
   - Keep the workflows if desired, but treat GitHub Releases as build output or internal release records, not as the public customer CDN.

4. Move public artifact URLs away from the private repo.
   - Set these Render environment variables to public, unauthenticated URLs:
     - `CONXA_RUNTIME_WIN_URL`
     - `CONXA_KEYTAR_WIN_URL`
     - `CONXA_STUDIO_WIN_URL`
   - If still used by any release path, also move `CONXA_RUNTIME_CDN_URL` to the public artifact base.
   - Recommended host: Conxa-owned object storage/CDN or a Conxa Cloud file endpoint.
   - Acceptable short-term fallback: a separate public release-only repo containing only binaries and checksums.

5. Do not embed GitHub credentials in shipped software.
   - Do not put GitHub PATs in Build Studio, the runtime, installers, frontend code, manifests, or query strings.
   - Do not make customer machines authenticate to GitHub just to update Conxa runtime files.
   - If private GitHub assets must remain the build source, copy them server-side into public Conxa-hosted artifact URLs before publishing manifests.

## What Probably Does Not Need To Change

- Local developer setup scripts use repo-local paths and public package registries, not public GitHub source downloads.
- The local git remote URL can remain `https://github.com/Cannonbold2412/AI_NATIVE.git`; developers just need GitHub authentication and repo access.
- The installer download route is separate from GitHub repo visibility. Conxa Cloud already serves installer downloads from its own API surface.
- The supported release path is Build Installer packaging, not a public `npx conxa install` or GitHub-published CLI flow.
- Package manifests and lockfiles mostly reference public dependency metadata; those are not affected by making this source repo private.

## Recommended Target Shape

Use this release flow after the repo becomes private:

1. GitHub Actions builds `runtime-win.exe`, `keytar.node`, and the Build Studio installer from the private repo.
2. CI uploads those binaries to Conxa-owned public artifact storage.
3. CI computes SHA-256 checksums.
4. CI updates the Cloud manifest values or Render environment variables with public artifact URLs and checksums.
5. Build Studio and runtime clients fetch only Conxa-hosted public URLs.

This keeps source private while preserving unauthenticated customer updates.

## Validation Checklist

- From a logged-out machine, open `GET /api/v1/updates/deps-manifest` and download every URL it returns.
- From a logged-out machine, open `GET /api/v1/updates/runtime-manifest` and download `url` and `keytar_url`.
- From a logged-out machine, open `GET /api/v1/updates/studio-manifest` and download `win_url`.
- Run Build Studio first-run bootstrap from a clean dependency cache and confirm it downloads NSIS, runtime, and keytar successfully.
- Start an installed runtime cold and confirm update check succeeds or safely no-ops.
- Trigger `runtime-v*` and `studio-v*` workflows and confirm the manifests point at public artifact URLs, not private GitHub Release URLs.
- Confirm Render deploys after the repo is private.
- Confirm Vercel deploys after the repo is private.

## External References

- GitHub repository visibility effects: <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility>
- GitHub release asset authentication: <https://docs.github.com/en/rest/releases/assets?apiVersion=2022-11-28>
- Render GitHub repository access: <https://render.com/docs/github>
- Vercel private Git repository rules: <https://vercel.com/docs/git>
- GitHub Actions private repository billing: <https://docs.github.com/en/billing/concepts/product-billing/github-actions>
