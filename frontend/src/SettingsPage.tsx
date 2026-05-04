'use client'

import { useQuery } from '@tanstack/react-query'
import { fetchAuditEvents, fetchMe } from '@/api/productApi'
import { AppShell } from '@/components/layout/AppLayout'
import { ActivityTimeline, ErrorState, LoadingState } from '@/components/product/ProductPrimitives'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function SettingsPage() {
  const meQ = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const auditQ = useQuery({ queryKey: ['auditEvents'], queryFn: () => fetchAuditEvents(50) })

  return (
    <AppShell title="Settings" description="Account, workspace, API environment, audit activity, and danger-zone controls." mainClassName="overflow-y-auto">
      <div className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-4 sm:px-6 xl:grid-cols-2">
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Workspace</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 p-4">
            {meQ.isLoading ? <LoadingState /> : null}
            {meQ.isError ? <ErrorState message={(meQ.error as Error).message} /> : null}
            {meQ.data ? (
              <>
                <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Workspace</p>
                  <p className="mt-1 text-sm text-white">{meQ.data.workspace.name}</p>
                  <p className="mt-0.5 font-mono text-xs text-zinc-500">{meQ.data.workspace.id}</p>
                </div>
                <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">User</p>
                  <p className="mt-1 text-sm text-white">{meQ.data.user.name ?? meQ.data.user.email ?? meQ.data.user.id}</p>
                  <p className="mt-0.5 text-xs text-zinc-500">{meQ.data.user.auth_provider}</p>
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Audit events</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {auditQ.isLoading ? <LoadingState /> : null}
            {auditQ.isError ? <ErrorState message={(auditQ.error as Error).message} /> : null}
            {auditQ.data ? (
              <ActivityTimeline
                rows={auditQ.data.audit_events.map((event) => ({
                  id: event.id,
                  title: event.action.replace(/_/g, ' '),
                  detail: `${event.resource_type}${event.resource_id ? ` · ${event.resource_id}` : ''}`,
                  at: formatTime(event.created_at),
                }))}
              />
            ) : null}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
