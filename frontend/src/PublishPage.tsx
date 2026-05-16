'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  disconnectGithub,
  fetchPlugins,
  getGithubStatus,
  normalizePluginList,
  previewPublish,
  publishPlugin,
  type Plugin,
  type PublishPayload,
  type PublishPreview,
  type PublishResult,
} from '@/api/pluginApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  Lock,
  RefreshCw,
  Upload,
  Unlock,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// GitHub connection card
// ─────────────────────────────────────────────────────────────────────────────

function GitHubConnectCard({ onConnect }: { onConnect: () => void }) {
  const qc = useQueryClient()
  const statusQ = useQuery({
    queryKey: ['github-status'],
    queryFn: getGithubStatus,
    staleTime: 10_000,
  })

  const disconnectMut = useMutation({
    mutationFn: disconnectGithub,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['github-status'] }),
  })

  // Listen for postMessage from the OAuth popup
  useEffect(() => {
    function handler(ev: MessageEvent) {
      if (ev.data?.type === 'github-oauth-success') {
        void qc.invalidateQueries({ queryKey: ['github-status'] })
        onConnect()
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [qc, onConnect])

  function openOAuth() {
    const popup = window.open('/api/github-connect', 'github-oauth', 'width=600,height=700')
    if (!popup) {
      // Popup blocked — fall back to same-window navigation
      window.location.href = '/api/github-connect'
    }
  }

  const status = statusQ.data

  return (
    <Card className="border-white/8 bg-white/[0.03] shadow-none">
      <CardHeader className="flex-row items-center justify-between border-b border-white/8 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-white">
          GitHub Connection
        </CardTitle>
        {status?.connected ? (
          <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
            Connected
          </Badge>
        ) : (
          <Badge variant="outline" className="border-zinc-500/30 bg-zinc-500/10 text-zinc-400">
            Not connected
          </Badge>
        )}
      </CardHeader>
      <CardContent className="pt-4">
        {statusQ.isLoading ? (
          <p className="text-sm text-zinc-500">Checking connection…</p>
        ) : status?.connected ? (
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm text-zinc-300">
              Signed in as <span className="font-mono text-white">@{status.login}</span>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="border-white/10 bg-white/5 text-zinc-300"
              onClick={() => disconnectMut.mutate()}
              disabled={disconnectMut.isPending}
            >
              {disconnectMut.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Disconnect
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-zinc-400">
              Connect your GitHub account to publish plugin repos with one click.
              Requires <span className="font-mono text-zinc-300">repo</span> and{' '}
              <span className="font-mono text-zinc-300">read:user</span> scopes.
            </p>
            <p className="text-xs text-zinc-500">
              You need a GitHub OAuth App registered with callback{' '}
              <span className="font-mono">http://localhost:8000/api/v1/integrations/github/callback</span>.
              Set <span className="font-mono">GITHUB_OAUTH_CLIENT_ID</span> and{' '}
              <span className="font-mono">GITHUB_OAUTH_CLIENT_SECRET</span> in your backend <span className="font-mono">.env</span>.
            </p>
            <Button size="sm" onClick={openOAuth} className="gap-2">
              Connect GitHub
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Publish dialog (per plugin)
// ─────────────────────────────────────────────────────────────────────────────

type VersionBump = 'patch' | 'minor' | 'major' | 'manual'

function PublishDialog({
  plugin,
  onClose,
  onPublished,
}: {
  plugin: Plugin
  onClose: () => void
  onPublished: () => void
}) {
  const qc = useQueryClient()
  const previewQ = useQuery({
    queryKey: ['publish-preview', plugin.id],
    queryFn: () => previewPublish(plugin.id),
    staleTime: 30_000,
  })

  const preview = previewQ.data
  const isFirstPublish = !plugin.repository_url

  const [bump, setBump] = useState<VersionBump>('patch')
  const [manualVersion, setManualVersion] = useState('')
  const [changelog, setChangelog] = useState('')
  const [repoName, setRepoName] = useState(plugin.slug)
  const [isPrivate, setIsPrivate] = useState(true)
  const [result, setResult] = useState<PublishResult | null>(null)
  const [copied, setCopied] = useState(false)

  const mut = useMutation({
    mutationFn: () => {
      const payload: PublishPayload = {
        version_bump: bump === 'manual' ? null : bump,
        manual_version: bump === 'manual' ? manualVersion : null,
        changelog,
        create_repo: isFirstPublish,
        repo_name: isFirstPublish ? repoName : null,
        private: isPrivate,
      }
      return publishPlugin(plugin.id, payload)
    },
    onSuccess: (data) => {
      setResult(data)
      void qc.invalidateQueries({ queryKey: ['plugins'] })
      void qc.invalidateQueries({ queryKey: ['publish-preview', plugin.id] })
      onPublished()
    },
  })

  const nextVersion =
    preview && bump !== 'manual'
      ? preview.next_versions[bump]
      : manualVersion || '?'

  function copySnippet() {
    if (!result) return
    void navigator.clipboard.writeText(result.install_snippet)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100 max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-white">
            {isFirstPublish ? 'Publish to GitHub' : 'Publish Update'}
            {' — '}
            <span className="font-mono text-zinc-300">{plugin.name}</span>
          </DialogTitle>
        </DialogHeader>

        {result ? (
          // ── Success state ──────────────────────────────────────────────────
          <div className="space-y-4 pt-2">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-4 text-emerald-400 shrink-0" />
                <p className="text-sm font-medium text-emerald-300">
                  v{result.version} published successfully
                </p>
              </div>
              <a
                href={result.repo_url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1.5 text-xs text-emerald-200/70 hover:text-emerald-200"
              >
                <ExternalLink className="size-3" />
                {result.repo_url}
              </a>
              {result.commit_sha ? (
                <p className="text-xs text-zinc-500 font-mono">{result.commit_sha.slice(0, 12)}</p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs text-zinc-400">Claude Code MCP install</Label>
              <div className="relative rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-xs text-zinc-300">
                <pre className="whitespace-pre-wrap break-all">{result.install_snippet}</pre>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  className="absolute top-2 right-2 text-zinc-500 hover:text-white"
                  onClick={copySnippet}
                >
                  {copied ? <CheckCircle2 className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
                </Button>
              </div>
            </div>

            <Button className="w-full" onClick={onClose}>Done</Button>
          </div>
        ) : (
          // ── Publish form ───────────────────────────────────────────────────
          <div className="space-y-4 pt-2">
            {previewQ.isLoading ? (
              <p className="text-sm text-zinc-500">Loading preview…</p>
            ) : null}

            {isFirstPublish && (
              <>
                <div className="space-y-1.5">
                  <Label className="text-zinc-300">Repository name</Label>
                  <Input
                    value={repoName}
                    onChange={(e) => setRepoName(e.target.value)}
                    placeholder={plugin.slug}
                    className="border-white/10 bg-white/5 text-zinc-100 font-mono"
                  />
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setIsPrivate(!isPrivate)}
                    className="flex items-center gap-2 text-sm text-zinc-300"
                  >
                    {isPrivate ? <Lock className="size-4 text-zinc-400" /> : <Unlock className="size-4 text-zinc-400" />}
                    {isPrivate ? 'Private repository' : 'Public repository'}
                  </button>
                </div>
              </>
            )}

            {!isFirstPublish && plugin.repository_url ? (
              <div className="flex items-center gap-2 text-xs text-zinc-500">
                <ExternalLink className="size-3" />
                <a href={plugin.repository_url} target="_blank" rel="noreferrer" className="hover:text-zinc-300 truncate">
                  {plugin.repository_url}
                </a>
                {plugin.last_published_version ? (
                  <Badge variant="outline" className="border-white/10 bg-white/5 text-zinc-400 shrink-0">
                    current: v{plugin.last_published_version}
                  </Badge>
                ) : null}
              </div>
            ) : null}

            {/* Version bump */}
            <div className="space-y-1.5">
              <Label className="text-zinc-300">Version</Label>
              <div className="grid grid-cols-4 gap-1.5">
                {(['patch', 'minor', 'major', 'manual'] as VersionBump[]).map((b) => (
                  <button
                    key={b}
                    onClick={() => setBump(b)}
                    className={cn(
                      'rounded-lg border px-2 py-1.5 text-xs font-medium transition-colors',
                      bump === b
                        ? 'border-white/20 bg-white/10 text-white'
                        : 'border-white/8 bg-white/[0.03] text-zinc-400 hover:text-zinc-200',
                    )}
                  >
                    {b === 'manual' ? 'Manual' : (
                      <>
                        <span className="capitalize">{b}</span>
                        {preview ? (
                          <span className="ml-1 text-zinc-500 font-mono">
                            v{preview.next_versions[b]}
                          </span>
                        ) : null}
                      </>
                    )}
                  </button>
                ))}
              </div>
              {bump === 'manual' && (
                <Input
                  value={manualVersion}
                  onChange={(e) => setManualVersion(e.target.value)}
                  placeholder="e.g. 2.0.0"
                  className="border-white/10 bg-white/5 text-zinc-100 font-mono mt-1"
                />
              )}
              {bump !== 'manual' && preview ? (
                <p className="text-xs text-zinc-500">
                  Will publish as <span className="font-mono text-zinc-300">v{nextVersion}</span>
                </p>
              ) : null}
            </div>

            {/* Changelog */}
            <div className="space-y-1.5">
              <Label className="text-zinc-300">Release notes</Label>
              <Textarea
                value={changelog}
                onChange={(e) => setChangelog(e.target.value)}
                placeholder="What changed in this release?"
                className="border-white/10 bg-white/5 text-zinc-100 min-h-[80px] resize-none"
              />
            </div>

            {mut.isError ? (
              <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                <XCircle className="size-4 shrink-0 text-red-400" />
                <p className="text-xs text-red-300">{(mut.error as Error).message}</p>
              </div>
            ) : null}

            <Button
              className="w-full"
              onClick={() => mut.mutate()}
              disabled={
                mut.isPending ||
                (bump === 'manual' && !manualVersion) ||
                (isFirstPublish && !repoName)
              }
            >
              {mut.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Publishing…
                </>
              ) : (
                <>
                  <Upload className="size-4" />
                  {isFirstPublish ? `Publish v${nextVersion} to GitHub` : `Publish v${nextVersion}`}
                </>
              )}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Plugin row in the publish list
// ─────────────────────────────────────────────────────────────────────────────

function PluginPublishRow({
  plugin,
  githubConnected,
}: {
  plugin: Plugin
  githubConnected: boolean
}) {
  const [dialogOpen, setDialogOpen] = useState(false)

  return (
    <>
      <div className="flex items-center justify-between gap-4 border-t border-white/6 px-4 py-3 first:border-t-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-white">{plugin.name}</p>
            {plugin.last_published_version ? (
              <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300 text-[10px] shrink-0">
                v{plugin.last_published_version}
              </Badge>
            ) : null}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-zinc-500">
            <span className="font-mono">{plugin.slug}</span>
            {plugin.build ? (
              <span>
                built{' '}
                {new Date(plugin.build.last_built_at * 1000).toLocaleDateString([], {
                  month: 'short', day: 'numeric',
                })}
              </span>
            ) : null}
            {plugin.repository_url ? (
              <a
                href={plugin.repository_url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 hover:text-zinc-300"
              >
                <ExternalLink className="size-3" />
                GitHub
              </a>
            ) : null}
          </div>
        </div>
        <Button
          size="sm"
          variant={plugin.repository_url ? 'outline' : 'default'}
          className={plugin.repository_url ? 'border-white/10 bg-white/5 text-zinc-300' : ''}
          disabled={!githubConnected}
          onClick={() => setDialogOpen(true)}
          title={!githubConnected ? 'Connect GitHub first' : undefined}
        >
          {plugin.repository_url ? (
            <>
              <RefreshCw className="size-3.5" />
              Publish update
            </>
          ) : (
            <>
              <Upload className="size-3.5" />
              Publish
            </>
          )}
        </Button>
      </div>

      {dialogOpen ? (
        <PublishDialog
          plugin={plugin}
          onClose={() => setDialogOpen(false)}
          onPublished={() => setDialogOpen(false)}
        />
      ) : null}
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export function PublishPage() {
  const qc = useQueryClient()
  const pluginsQ = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
    staleTime: 10_000,
  })
  const statusQ = useQuery({
    queryKey: ['github-status'],
    queryFn: getGithubStatus,
    staleTime: 10_000,
  })

  const plugins = normalizePluginList(pluginsQ.data)
  const builtPlugins = plugins.filter((p) => p.build != null)
  const githubConnected = statusQ.data?.connected ?? false

  return (
    <AppShell
      title="Publish & Deploy"
      description="Publish plugin bundles to GitHub for one-click MCP install."
      mainClassName="overflow-y-auto"
    >
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6">
        {/* GitHub connection */}
        <GitHubConnectCard onConnect={() => void qc.invalidateQueries({ queryKey: ['plugins'] })} />

        {/* Plugins list */}
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8 pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-white">
              Built Plugins
              <Badge variant="outline" className="border-white/10 bg-white/5 text-zinc-400">
                {builtPlugins.length}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {pluginsQ.isLoading ? (
              <p className="px-4 py-6 text-sm text-zinc-500">Loading plugins…</p>
            ) : builtPlugins.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                <p className="text-sm text-zinc-400">No built plugins yet</p>
                <p className="max-w-xs text-xs text-zinc-600">
                  Build a plugin first using the{' '}
                  <Link href="/build" className="text-zinc-400 underline hover:text-zinc-200">
                    Build page
                  </Link>
                  , then come back here to publish it to GitHub.
                </p>
              </div>
            ) : (
              builtPlugins.map((plugin) => (
                <PluginPublishRow
                  key={plugin.id}
                  plugin={plugin}
                  githubConnected={githubConnected}
                />
              ))
            )}
          </CardContent>
        </Card>

        {/* Setup instructions */}
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8 pb-3">
            <CardTitle className="text-sm font-medium text-white">Setup Instructions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 pt-4 text-xs text-zinc-400">
            <p>
              <span className="font-medium text-zinc-200">1. Register a GitHub OAuth App</span> at{' '}
              <span className="font-mono text-zinc-300">github.com/settings/developers</span>.
              Set the callback URL to{' '}
              <span className="font-mono text-zinc-300">
                http://localhost:8000/api/v1/integrations/github/callback
              </span>.
            </p>
            <p>
              <span className="font-medium text-zinc-200">2. Add to your backend <span className="font-mono">.env</span>:</span>
            </p>
            <pre className="rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-zinc-300 whitespace-pre-wrap">
{`GITHUB_OAUTH_CLIENT_ID=your_client_id
GITHUB_OAUTH_CLIENT_SECRET=your_client_secret`}
            </pre>
            <p>
              <span className="font-medium text-zinc-200">3.</span> Restart the backend, then click{' '}
              <span className="font-mono text-zinc-300">Connect GitHub</span> above.
            </p>
            <p>
              <span className="font-medium text-zinc-200">4. After publishing,</span> install in Claude Code:{' '}
              <span className="font-mono text-zinc-300">Settings → MCP Servers → Add from GitHub</span>.
            </p>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
