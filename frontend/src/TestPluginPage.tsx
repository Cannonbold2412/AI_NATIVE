'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import {
  fetchPlugins,
  normalizePluginList,
} from '@/api/pluginApi'
import { PluginWorkflowTests, workflowTestSummary } from '@/components/PluginWorkflowTests'
import { PageHeader } from '@/components/layout/PageHeader'
import { cn } from '@/lib/utils'

export function TestPluginPage() {
  const pluginsQ = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
    staleTime: 30_000,
  })

  const [selectedId, setSelectedId] = useState<string | null>(null)

  const plugins = useMemo(() => normalizePluginList(pluginsQ.data), [pluginsQ.data])
  const builtPlugins = useMemo(() => plugins.filter((p) => p.build), [plugins])
  const selectedPlugin = useMemo(() => {
    if (builtPlugins.length === 0) return null
    if (selectedId) return builtPlugins.find((p) => p.id === selectedId) ?? builtPlugins[0]
    return builtPlugins[0] ?? null
  }, [builtPlugins, selectedId])

  function onTestComplete() {
    void pluginsQ.refetch()
  }

  if (pluginsQ.isLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Test Plugin" />
        <p className="p-6 text-sm text-zinc-500">Loading...</p>
      </div>
    )
  }

  if (pluginsQ.isError || !pluginsQ.data) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Test Plugin" />
        <p className="p-6 text-sm text-red-400">{(pluginsQ.error as Error)?.message ?? 'Failed to load plugins'}</p>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="Test Plugin"
        description="Run each workflow end-to-end against the built bundle. All workflows must pass before Build Installer is enabled."
      />
      <div className="flex min-h-0 flex-1 gap-4 p-6">
        {/* Left: plugin list */}
        <div className="flex min-h-0 w-72 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          <div className="border-b border-white/8 px-4 py-3">
            <h2 className="text-sm font-medium text-white">Built Plugins</h2>
            <p className="mt-0.5 text-xs text-zinc-500">{builtPlugins.length} built</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            {builtPlugins.length === 0 ? (
              <div className="px-2 py-4 text-xs text-zinc-500">
                <p>No built plugins yet.</p>
                <Link href="/build" className="mt-1 block underline">
                  Go to Build Plugin
                </Link>
              </div>
            ) : (
              <div className="space-y-1">
                {builtPlugins.map((plugin) => {
                  const { allPassed, passed: passedCount, total } = workflowTestSummary(plugin)
                  const selected = selectedPlugin?.id === plugin.id
                  return (
                    <button
                      key={plugin.id}
                      type="button"
                      onClick={() => setSelectedId(plugin.id)}
                      className={cn(
                        'w-full cursor-pointer rounded-lg border border-transparent px-3 py-2.5 text-left text-sm transition-colors',
                        'hover:border-white/8 hover:bg-white/[0.07] hover:text-white',
                        selected ? 'border-white/10 bg-white/[0.10] text-white' : 'text-zinc-300',
                      )}
                    >
                      <p className="truncate font-medium">{plugin.name}</p>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {passedCount}/{total} workflows passed
                      </p>
                      {allPassed && (
                        <p className="mt-0.5 text-xs text-emerald-400">Ready for installer</p>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right: workflow list */}
        <div className="flex min-h-0 flex-1 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          {selectedPlugin ? (
            <>
              <div className="border-b border-white/8 px-4 py-3">
                <h3 className="text-sm font-medium text-white">{selectedPlugin.name}</h3>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {selectedPlugin.workflows.length} workflow{selectedPlugin.workflows.length !== 1 ? 's' : ''}
                </p>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
                <PluginWorkflowTests plugin={selectedPlugin} onComplete={onTestComplete} />
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-zinc-500">Select a built plugin to test its workflows.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
