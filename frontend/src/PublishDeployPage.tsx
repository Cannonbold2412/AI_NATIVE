'use client'

import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { fetchSkillPackageList } from '@/api/workflowApi'
import { fetchRelease, patchRelease, publishBundle } from '@/api/productApi'
import { AppShell } from '@/components/layout/AppLayout'
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '@/components/product/ProductPrimitives'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Archive, Rocket } from 'lucide-react'

export function PublishDeployPage() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [version, setVersion] = useState('0.1.0')
  const [notes, setNotes] = useState('')
  const packagesQ = useQuery({ queryKey: ['skillPackages'], queryFn: fetchSkillPackageList })
  const selectedSlug = selected ?? packagesQ.data?.packages[0]?.package_name ?? null
  const releaseQ = useQuery({
    queryKey: ['packageRelease', selectedSlug],
    queryFn: () => fetchRelease(selectedSlug ?? ''),
    enabled: Boolean(selectedSlug),
  })
  const currentPkg = useMemo(
    () => packagesQ.data?.packages.find((pkg) => pkg.package_name === selectedSlug) ?? null,
    [packagesQ.data?.packages, selectedSlug],
  )

  async function publish() {
    if (!selectedSlug) return
    try {
      await publishBundle(selectedSlug, { version, release_notes: notes })
      toast.success(`${selectedSlug} published`)
      await qc.invalidateQueries({ queryKey: ['packageRelease', selectedSlug] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not publish package')
    }
  }

  async function archive() {
    if (!selectedSlug) return
    try {
      await patchRelease(selectedSlug, { state: 'archived' })
      toast.success(`${selectedSlug} archived`)
      await qc.invalidateQueries({ queryKey: ['packageRelease', selectedSlug] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not archive package')
    }
  }

  return (
    <AppShell title="Publish & Deploy" description="Package readiness, release notes, version metadata, and install instructions." mainClassName="overflow-y-auto">
      <div className="mx-auto grid w-full max-w-7xl gap-4 px-4 py-4 sm:px-6 xl:grid-cols-[18rem_minmax(0,1fr)]">
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Packages</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-3">
            {packagesQ.isLoading ? <LoadingState /> : null}
            {packagesQ.isError ? <ErrorState message={(packagesQ.error as Error).message} /> : null}
            {packagesQ.data?.packages.length === 0 ? <EmptyState title="No packages" /> : null}
            {packagesQ.data?.packages.map((pkg) => (
              <button
                key={pkg.package_name}
                type="button"
                className="w-full rounded-lg border border-white/8 bg-black/20 px-3 py-2 text-left transition-colors hover:bg-white/[0.05]"
                onClick={() => setSelected(pkg.package_name)}
              >
                <p className="truncate text-sm font-medium text-white">{pkg.package_name}</p>
                <p className="mt-0.5 text-xs text-zinc-500">{pkg.workflows.length} workflows</p>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <CardTitle className="text-white">{selectedSlug ?? 'Release'}</CardTitle>
              {releaseQ.data ? <StatusBadge status={releaseQ.data.release.state} /> : null}
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 p-4">
            {!selectedSlug ? <EmptyState title="Select a package" /> : null}
            {selectedSlug && currentPkg ? (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-300">{currentPkg.workflows.length} workflows</div>
                  <div className="rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-300">{currentPkg.files.length} files</div>
                  <div className="rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-300">ZIP install ready</div>
                </div>
                <div className="grid gap-2">
                  <label className="text-xs uppercase tracking-[0.16em] text-zinc-500" htmlFor="release-version">Version</label>
                  <Input id="release-version" value={version} onChange={(event) => setVersion(event.target.value)} className="border-white/10 bg-black/20 text-zinc-100" />
                </div>
                <div className="grid gap-2">
                  <label className="text-xs uppercase tracking-[0.16em] text-zinc-500" htmlFor="release-notes">Release notes</label>
                  <Textarea id="release-notes" value={notes} onChange={(event) => setNotes(event.target.value)} className="min-h-36 border-white/10 bg-black/20 text-zinc-100" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => void publish()}>
                    <Rocket className="size-4" />
                    Publish
                  </Button>
                  <Button variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-200" onClick={() => void archive()}>
                    <Archive className="size-4" />
                    Archive
                  </Button>
                </div>
                <pre className="rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-xs text-zinc-300">
                  {`cd output/skill_package/${selectedSlug}\nnode install.js\nrender "<your request>"`}
                </pre>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
