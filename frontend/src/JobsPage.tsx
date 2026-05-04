'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { cancelJob, fetchJobs } from '@/api/productApi'
import { AppShell } from '@/components/layout/AppLayout'
import { DataTable, EmptyState, ErrorState, LoadingState, StatusBadge } from '@/components/product/ProductPrimitives'
import { Button } from '@/components/ui/button'
import { RefreshCw, XCircle } from 'lucide-react'

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function JobsPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['jobs'], queryFn: fetchJobs, refetchInterval: 5000 })

  async function handleCancel(jobId: string) {
    try {
      await cancelJob(jobId)
      toast.success('Job canceled')
      await qc.invalidateQueries({ queryKey: ['jobs'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not cancel job')
    }
  }

  return (
    <AppShell
      title="Jobs"
      description="Queued, running, completed, failed, and canceled worker-backed operations."
      mainClassName="overflow-y-auto"
      actions={
        <Button variant="outline" size="sm" className="border-white/10 bg-white/[0.04] text-zinc-200" onClick={() => void q.refetch()}>
          <RefreshCw className="size-3.5" />
          Refresh
        </Button>
      }
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6">
        {q.isLoading ? <LoadingState label="Loading jobs" /> : null}
        {q.isError ? <ErrorState message={(q.error as Error).message} /> : null}
        {q.data?.jobs.length === 0 ? <EmptyState title="No jobs yet" description="Compile and package builds can be queued from recorder and builder flows." /> : null}
        {q.data && q.data.jobs.length > 0 ? (
          <DataTable>
            <div className="grid grid-cols-[minmax(0,1fr)_8rem_9rem_9rem_7rem] gap-3 border-b border-white/8 px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-zinc-500">
              <span>Job</span>
              <span>Status</span>
              <span>Created</span>
              <span>Updated</span>
              <span className="text-right">Action</span>
            </div>
            {q.data.jobs.map((job) => (
              <div key={job.job_id} className="grid grid-cols-[minmax(0,1fr)_8rem_9rem_9rem_7rem] items-center gap-3 border-b border-white/6 px-4 py-3 last:border-b-0">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">{job.kind}</p>
                  <p className="truncate font-mono text-xs text-zinc-500">{job.resource_id ?? job.job_id}</p>
                  {job.user_error ? <p className="mt-1 text-xs text-red-200">{job.user_error}</p> : null}
                </div>
                <StatusBadge status={job.status} />
                <p className="text-xs text-zinc-400">{formatTime(job.created_at)}</p>
                <p className="text-xs text-zinc-400">{formatTime(job.updated_at)}</p>
                <div className="flex justify-end">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    className="text-zinc-400 hover:bg-red-500/10 hover:text-red-200"
                    disabled={['succeeded', 'failed', 'canceled'].includes(job.status)}
                    onClick={() => void handleCancel(job.job_id)}
                    aria-label={`Cancel ${job.job_id}`}
                  >
                    <XCircle className="size-4" />
                  </Button>
                </div>
              </div>
            ))}
          </DataTable>
        ) : null}
      </div>
    </AppShell>
  )
}
