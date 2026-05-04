'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  errorMessage,
  fetchSkillList,
  fetchSkillPackageList,
  fetchWorkflow,
  SkillPackBuildRequestError,
  type SkillPackageSummary,
} from '@/api/workflowApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  appendWorkflowToSkillPackage,
  buildSkillPackage,
  downloadSkillPackZip,
  type SkillPackBuildLogEntry,
  type SkillPackBuildResult,
} from '@/services/skillPackBuilder'
import { CheckCircle2, Download, LoaderCircle, Package, X } from 'lucide-react'

const GENERATION_PROGRESS_INTERVAL_MS = 250
const NO_PACKAGE_SENTINEL = '__no_package_selected__'
const NO_APPEND_WORKFLOW_SENTINEL = '__no_append_workflow__'

function bundleSummaryLine(pkg: SkillPackageSummary): string {
  const n = pkg.workflows.length
  return `${n} workflow folder${n === 1 ? '' : 's'}`
}

function workflowFilesTotal(pkg: SkillPackageSummary): number {
  return pkg.workflows.reduce((acc, wf) => acc + wf.files.length, 0)
}

function AppendPackageTriggerValue({ pkg }: { pkg: SkillPackageSummary }) {
  const files = workflowFilesTotal(pkg)
  return (
    <span className="flex min-w-0 w-full items-center gap-2 text-left">
      <span className="min-w-0 truncate font-medium">{pkg.package_name}</span>
      <span className="shrink-0 text-xs text-zinc-500">
        {bundleSummaryLine(pkg)} · {files} file{files === 1 ? '' : 's'}
      </span>
    </span>
  )
}

function formatDurationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (remainder === 0) return `${minutes}m`
  return `${minutes}m ${remainder}s`
}

function shortTimeNow(): string {
  return new Date().toLocaleTimeString(undefined, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatSkillPackLogLine(entry: SkillPackBuildLogEntry): string {
  const t =
    typeof entry.ts === 'number' && Number.isFinite(entry.ts)
      ? new Date(entry.ts * 1000).toLocaleTimeString(undefined, {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      : shortTimeNow()
  const kind = entry.kind
  switch (kind) {
    case 'llm_request_sent': {
      const host = entry.host != null ? String(entry.host) : '—'
      const path = entry.path != null ? String(entry.path) : ''
      const model = entry.model != null ? String(entry.model) : '—'
      const to = entry.timeout_ms != null ? Number(entry.timeout_ms) : 0
      const bytes = entry.payload_bytes != null ? Number(entry.payload_bytes) : 0
      const att = entry.attempt != null ? Number(entry.attempt) : 1
      const steps = entry.raw_step_count != null ? Number(entry.raw_step_count) : null
      const maxA = entry.max_attempts != null ? Number(entry.max_attempts) : null
      const strict = entry.strict_json_response === true ? 'response_format=json_object' : 'response_format=off'
      const pathBit = path ? ` ${path}` : ''
      const stepsBit = steps != null && Number.isFinite(steps) ? `  rawSteps=${steps}` : ''
      const maxBit = maxA != null && Number.isFinite(maxA) ? `  maxAttempts=${maxA}` : ''
      return `[${t}] LLM request sent  #${att}  ${host}${pathBit}  model=${model}  ${strict}  timeout=${Math.round(to / 1000)}s  payload≈${Math.max(1, Math.round(bytes / 1024))}KB${stepsBit}${maxBit}`
    }
    case 'llm_response_received': {
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      const ch = entry.response_chars != null ? Number(entry.response_chars) : 0
      return `[${t}] LLM response received  ${ms}ms  ${ch} chars`
    }
    case 'llm_http_error': {
      const st = entry.status != null ? Number(entry.status) : '—'
      const rs = entry.reason != null ? String(entry.reason) : ''
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      const prev =
        entry.response_body_preview != null && String(entry.response_body_preview).trim()
          ? String(entry.response_body_preview).trim().replace(/\s+/g, ' ')
          : ''
      const prevShort = prev.length > 280 ? `${prev.slice(0, 280)}…` : prev
      const bodyBit = prevShort ? `  body≈${prevShort}` : ''
      return `[${t}] LLM HTTP error  ${st} ${rs}  ${ms}ms${bodyBit}`
    }
    case 'llm_retry': {
      const att = entry.attempt != null ? Number(entry.attempt) : 1
      const reason = entry.reason != null ? String(entry.reason) : ''
      return `[${t}] LLM retry  #${att}  ${reason}`
    }
    case 'llm_timeout': {
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      const to = entry.timeout_ms != null ? Number(entry.timeout_ms) : 0
      const path = entry.path != null ? String(entry.path) : ''
      const steps = entry.raw_step_count != null ? Number(entry.raw_step_count) : null
      const pathBit = path ? `  ${path}` : ''
      const stepsBit = steps != null && Number.isFinite(steps) ? `  rawSteps=${steps}` : ''
      return `[${t}] LLM timeout  limit=${Math.round(to / 1000)}s  waited ${ms}ms${pathBit}${stepsBit}`
    }
    case 'llm_network_error': {
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      const d = entry.detail != null ? String(entry.detail) : ''
      return `[${t}] LLM network error  ${ms}ms  ${d}`
    }
    case 'llm_response_parsed': {
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      const ch = entry.response_chars != null ? Number(entry.response_chars) : 0
      const keys = entry.top_level_keys
      const est = entry.dict_key_estimate != null ? Number(entry.dict_key_estimate) : null
      const keyBit =
        Array.isArray(keys) && keys.length > 0
          ? ` keys=[${keys.slice(0, 8).join(',')}${keys.length > 8 ? '…' : ''}]`
          : est != null && Number.isFinite(est)
            ? ` keys≈${est}`
            : ''
      return `[${t}] LLM response JSON parsed  ${ms}ms  ${ch} chars${keyBit}`
    }
    case 'pipeline_phase': {
      const phase = entry.phase != null ? String(entry.phase) : '—'
      const state = entry.state != null ? String(entry.state) : '—'
      const wf = entry.workflow_title != null ? String(entry.workflow_title) : ''
      const bits: string[] = []
      if (entry.elapsed_ms != null && Number.isFinite(Number(entry.elapsed_ms))) bits.push(`${Number(entry.elapsed_ms)}ms`)
      if (entry.raw_step_count != null) bits.push(`raw=${entry.raw_step_count}`)
      if (entry.canonical_step_count != null) bits.push(`structured=${entry.canonical_step_count}`)
      if (entry.execution_plan_steps != null) bits.push(`exec=${entry.execution_plan_steps}`)
      if (entry.input_slots != null) bits.push(`inputs=${entry.input_slots}`)
      if (entry.recovery_entries != null) bits.push(`recovery=${entry.recovery_entries}`)
      if (entry.json_chars != null) bits.push(`json≈${Math.max(1, Math.round(Number(entry.json_chars) / 1024))}KB`)
      if (entry.visual_assets != null) bits.push(`visuals=${entry.visual_assets}`)
      const tail = bits.length ? `  ${bits.join(' ')}` : ''
      return `[${t}] Pipeline ${phase} · ${state}${wf ? ` · ${wf}` : ''}${tail}`
    }
    case 'bundle_compile_outline': {
      const n = entry.workflow_count != null ? Number(entry.workflow_count) : 0
      return `[${t}] Bundle compile • ${n} workflow segment(s)`
    }
    case 'workflow_compile_start': {
      const i = entry.index != null ? Number(entry.index) : 0
      const tot = entry.total != null ? Number(entry.total) : 0
      const title = entry.title != null ? String(entry.title) : ''
      const rs = entry.raw_steps != null ? Number(entry.raw_steps) : 0
      return `[${t}] Workflow ${i}/${tot} → compile start · ${title} · ${rs} raw steps`
    }
    case 'workflow_compile_complete': {
      const i = entry.index != null ? Number(entry.index) : 0
      const tot = entry.total != null ? Number(entry.total) : 0
      const pkg = entry.package_name != null ? String(entry.package_name) : ''
      return `[${t}] Workflow ${i}/${tot} → compile done · folder ${pkg}`
    }
    case 'persist_phase': {
      const st = entry.state != null ? String(entry.state) : ''
      const bun = entry.bundle_slug != null ? String(entry.bundle_slug) : ''
      const wn = entry.workflow_names
      const names =
        Array.isArray(wn) && wn.length > 0
          ? ` · ${wn.map((x) => String(x)).join(', ')}`
          : ''
      return `[${t}] Disk persist ${st}${bun ? ` · bundle=${bun}` : ''}${names}`
    }
    case 'file_written': {
      const p = entry.path != null ? String(entry.path) : '?'
      const b = entry.bytes != null ? Number(entry.bytes) : 0
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      return `[${t}] Wrote ${p}  (${b} B)  ${ms}ms`
    }
    case 'bundle_artifact_updated': {
      const p = entry.path != null ? String(entry.path) : '?'
      const ms = entry.elapsed_ms != null ? Number(entry.elapsed_ms) : 0
      return `[${t}] Updated ${p}  ${ms}ms`
    }
    default:
      return `[${t}] ${JSON.stringify(entry)}`
  }
}

export function SkillPackBuilderPage() {
  const [packageMode, setPackageMode] = useState<'merge' | 'append'>('merge')
  /** Nested folder under output/skill_package/<bundleName>/ holding README, engine, workflows/. */
  const [bundleNameInput, setBundleNameInput] = useState('')
  const [selectedBundleName, setSelectedBundleName] = useState('')
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])
  /** In append mode, workflow is staged here until the user clicks the append button (no API until then). */
  const [appendStagedSkillId, setAppendStagedSkillId] = useState<string | null>(null)
  const [workflowLoadErrors, setWorkflowLoadErrors] = useState<Record<string, string>>({})
  const [isGenerating, setIsGenerating] = useState(false)
  const [isAppending, setIsAppending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SkillPackBuildResult | null>(null)
  const [createdWorkflowNames, setCreatedWorkflowNames] = useState<string[]>([])
  const [generationStartedAt, setGenerationStartedAt] = useState<number | null>(null)
  const [generationNow, setGenerationNow] = useState<number | null>(null)
  const [terminalLines, setTerminalLines] = useState<string[]>([])
  /** Remount Radix Select so it resets after picking (avoids trapping value on a fake sentinel). */
  const [workflowPickResetKey, setWorkflowPickResetKey] = useState(0)
  const terminalRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()

  const skillsQ = useQuery({
    queryKey: ['skillList'],
    queryFn: fetchSkillList,
    staleTime: 60_000,
  })

  const packagesQ = useQuery({
    queryKey: ['skillPackagesForBuilder'],
    queryFn: fetchSkillPackageList,
    staleTime: 30_000,
  })

  const sortedSkills = useMemo(() => {
    const skills = [...(skillsQ.data?.skills ?? [])]
    skills.sort((a, b) => b.modified_at - a.modified_at)
    return skills
  }, [skillsQ.data?.skills])

  const sortedPackages = useMemo(() => {
    const packages = [...(packagesQ.data?.packages ?? [])]
    packages.sort((a, b) => b.modified_at - a.modified_at)
    return packages
  }, [packagesQ.data?.packages])

  const appendTargetPackage = useMemo(
    () => sortedPackages.find((p) => p.package_name === selectedBundleName),
    [sortedPackages, selectedBundleName],
  )

  const availableSkillsToAdd = useMemo(
    () => sortedSkills.filter((skill) => !selectedSkillIds.includes(skill.skill_id)),
    [sortedSkills, selectedSkillIds],
  )

  const isBuildBusy = isGenerating || isAppending

  const generationElapsedSeconds = useMemo(() => {
    if (!isBuildBusy || generationStartedAt == null || generationNow == null) return 0
    return Math.max(0, (generationNow - generationStartedAt) / 1000)
  }, [generationNow, generationStartedAt, isBuildBusy])

  const generationProgressValue = useMemo(() => {
    const estimate = 20
    if (!isBuildBusy) return 0
    if (estimate <= 0) return 12
    const ratio = generationElapsedSeconds / estimate
    if (ratio >= 1) return 96
    return Math.max(8, Math.min(96, Math.round((ratio ** 0.82) * 92)))
  }, [generationElapsedSeconds, isBuildBusy])

  const generationStatusLabel = useMemo(() => {
    if (!isBuildBusy) return null
    if (isAppending) return 'Appending workflow to bundle…'
    return 'Preparing package build…'
  }, [isAppending, isBuildBusy])

  const generationCaption = useMemo(() => {
    if (!isBuildBusy) return null
    const elapsed = formatDurationLabel(Math.max(1, Math.floor(generationElapsedSeconds)))
    return `Elapsed ${elapsed}`
  }, [generationElapsedSeconds, isBuildBusy])

  useEffect(() => {
    if (!isBuildBusy || generationStartedAt == null) {
      setGenerationNow(null)
      return
    }
    setGenerationNow(Date.now())
    const timer = window.setInterval(() => setGenerationNow(Date.now()), GENERATION_PROGRESS_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [generationStartedAt, isBuildBusy])

  useEffect(() => {
    const el = terminalRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [terminalLines])

  async function loadWorkflowsForSkills(skillIds: string[]) {
    if (skillIds.length === 0) {
      setSelectedSkillIds([])
      setWorkflowLoadErrors({})
      setError(null)
      return
    }
    setSelectedSkillIds(skillIds)
    setWorkflowLoadErrors({})
    setError(null)
    setCreatedWorkflowNames([])
    setResult(null)
    if (skillIds.length === 1) {
      toast.success('Selected workflow will build into its own folder.')
      return
    }
    toast.success(`${skillIds.length} workflows selected. Each will build into its own folder.`)
  }

  function loadSelectedBundle(bundleSlug: string) {
    if (!bundleSlug) {
      setSelectedBundleName('')
      setAppendStagedSkillId(null)
      return
    }
    setSelectedBundleName(bundleSlug)
    setAppendStagedSkillId(null)
    setWorkflowLoadErrors({})
    setSelectedSkillIds([])
    setError(null)
    setCreatedWorkflowNames([])
    setResult(null)
    toast.success(`Selected bundle "${bundleSlug}" for appending workflows.`)
  }

  async function mergeSkillSelection(skillId: string) {
    if (selectedSkillIds.includes(skillId)) {
      toast.error('This workflow is already in the merge list.')
      return
    }
    await loadWorkflowsForSkills([...selectedSkillIds, skillId])
  }

  async function performAppendWorkflow(
    skillId: string,
    onStreamLog?: (entry: SkillPackBuildLogEntry) => void,
  ): Promise<boolean> {
    if (!selectedBundleName) {
      toast.error('Select an existing skill package bundle first, then append a workflow.')
      return false
    }
    if (selectedSkillIds.includes(skillId)) {
      toast.error('This skill is already in the current package.')
      return false
    }

    try {
      const workflow = await fetchWorkflow(skillId)
      const skill = sortedSkills.find((s) => s.skill_id === skillId)
      setTerminalLines((prev) => [
        ...prev,
        `[${shortTimeNow()}] Loaded "${skill?.title ?? skillId}" (${JSON.stringify(workflow).length} chars)`,
        `[${shortTimeNow()}] Streaming POST /skill-pack/bundles/${selectedBundleName}/append/stream`,
      ])
      const updated = await appendWorkflowToSkillPackage(
        selectedBundleName,
        JSON.stringify(workflow),
        undefined,
        onStreamLog ? { onLog: onStreamLog } : undefined,
      )
      setResult(updated)
      setCreatedWorkflowNames([updated.name])
      setSelectedSkillIds((prev) => [...prev, skillId])
      setWorkflowLoadErrors((prev) => {
        const next = { ...prev }
        delete next[skillId]
        return next
      })
      setError(null)
      void qc.invalidateQueries({ queryKey: ['skillPackagesForBuilder'] })
      toast.success(`Added workflow folder "${updated.name}" to the shared bundle.`)
      return true
    } catch (err) {
      const message =
        err instanceof SkillPackBuildRequestError
          ? err.message
          : errorMessage(err, 'Could not append workflow.')
      setError(message)
      setTerminalLines((prev) => {
        const tail: string[] = []
        if (err instanceof SkillPackBuildRequestError && err.buildLog.length > 0) {
          tail.push(...err.buildLog.map(formatSkillPackLogLine))
        }
        tail.push(`[${shortTimeNow()}] ERROR: ${message}`)
        return [...prev, ...tail]
      })
      setWorkflowLoadErrors((prev) => ({ ...prev, [skillId]: message }))
      toast.error(message)
      return false
    }
  }

  function removeSkillSelection(skillId: string) {
    const nextSkillIds = selectedSkillIds.filter((id) => id !== skillId)
    if (packageMode === 'merge') {
      void loadWorkflowsForSkills(nextSkillIds)
      return
    }
    setSelectedSkillIds(nextSkillIds)
  }

  async function handleGenerate() {
    if (packageMode === 'append') {
      if (!selectedBundleName) {
        toast.error('Select an existing skill package bundle first.')
        return
      }
      if (!appendStagedSkillId) {
        toast.error('Choose a workflow to append, then click append.')
        return
      }
      const staged = appendStagedSkillId
      const skill = sortedSkills.find((s) => s.skill_id === staged)
      setIsAppending(true)
      setGenerationStartedAt(Date.now())
      setGenerationNow(Date.now())
      setError(null)
      const runStarted = Date.now()
      setTerminalLines([
        `[${shortTimeNow()}] Appending "${skill?.title ?? staged}" -> bundle "${selectedBundleName}"`,
      ])
      try {
        const ok = await performAppendWorkflow(staged, (row) =>
          setTerminalLines((p) => [...p, formatSkillPackLogLine(row)]),
        )
        if (ok) {
          setTerminalLines((prev) => [
            ...prev,
            `[${shortTimeNow()}] Append finished in ${formatDurationMs(Date.now() - runStarted)}`,
          ])
          setAppendStagedSkillId(null)
          setWorkflowPickResetKey((k) => k + 1)
        }
      } finally {
        setIsAppending(false)
        setGenerationStartedAt(null)
        setGenerationNow(null)
      }
      return
    }
    const bundleSlug = bundleNameInput.trim()
    if (!bundleSlug) {
      toast.error('Enter a skill package folder name (saved under output/skill_package/<name>/).')
      return
    }
    if (selectedSkillIds.length === 0) {
      toast.error('Select at least one saved workflow.')
      return
    }
    setIsGenerating(true)
    setGenerationStartedAt(Date.now())
    setGenerationNow(Date.now())
    setError(null)
    setTerminalLines([])
    const runStarted = Date.now()
    try {
      const lines: string[] = [
        `[${shortTimeNow()}] Starting bundle "${bundleSlug}" — ${selectedSkillIds.length} workflow folder(s)`,
      ]
      setTerminalLines(lines)
      const built: string[] = []
      let last: SkillPackBuildResult | null = null
      lines.push(`[${shortTimeNow()}] Fetching ${selectedSkillIds.length} workflow(s) in parallel…`)
      setTerminalLines([...lines])
      const fetched = await Promise.all(
        selectedSkillIds.map(async (skillId, i) => {
          const skill = sortedSkills.find((s) => s.skill_id === skillId)
          const workflow = await fetchWorkflow(skillId)
          return { skillId, skill, workflow, index: i }
        }),
      )
      for (const { skill, workflow, index, skillId } of fetched) {
        lines.push(
          `[${shortTimeNow()}] (${index + 1}/${fetched.length}) Loaded "${skill?.title ?? skillId}" (${JSON.stringify(workflow).length} chars)`,
        )
      }
      lines.push(
        `[${shortTimeNow()}] Streaming POST /skill-pack/build/stream — ${fetched.length} workflow(s) sequentially (live log lines; bundle index still locked per bundle)`,
      )
      setTerminalLines([...lines])
      for (const { workflow, index, skill, skillId } of fetched) {
        const wfStarted = Date.now()
        setTerminalLines((prev) => [
          ...prev,
          `[${shortTimeNow()}] (${index + 1}/${fetched.length}) Stream build: "${skill?.title ?? skillId}"`,
        ])
        const next = await buildSkillPackage(JSON.stringify(workflow), undefined, bundleSlug, {
          onLog: (row) => setTerminalLines((p) => [...p, formatSkillPackLogLine(row)]),
        })
        setTerminalLines((prev) => [
          ...prev,
          `[${shortTimeNow()}] Workflow folder "${next.name}" finished in ${formatDurationMs(Date.now() - wfStarted)}`,
        ])
        built.push(next.name)
        last = next
      }
      if (!last) {
        throw new Error('No workflows were selected for bundle generation.')
      }
      lines.push(`[${shortTimeNow()}] All workflows done in ${formatDurationMs(Date.now() - runStarted)}`)
      setTerminalLines([...lines])
      setResult(last)
      setCreatedWorkflowNames(built)
      toast.success(`${built.length} workflow folder(s) generated under output/skill_package/${bundleSlug}/workflows/.`)
    } catch (err) {
      const message =
        err instanceof SkillPackBuildRequestError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not generate Skill Package.'
      setError(message)
      setTerminalLines((prev) => {
        const tail: string[] = []
        if (err instanceof SkillPackBuildRequestError && err.buildLog.length > 0) {
          tail.push(...err.buildLog.map(formatSkillPackLogLine))
        }
        tail.push(`[${shortTimeNow()}] ERROR: ${message}`)
        return [...prev, ...tail]
      })
      toast.error(message)
    } finally {
      setIsGenerating(false)
      setGenerationStartedAt(null)
      setGenerationNow(null)
    }
  }

  async function handleZipDownload() {
    if (!result) return
    try {
      await downloadSkillPackZip(result)
      toast.success('Skill package zip downloaded.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not export zip.'
      toast.error(message)
    }
  }

  return (
    <AppShell
      title="Skill Pack Builder"
      description="Build workflow folders inside a named package: output/skill_package/<package_name>/workflows/<workflow_slug>. Append adds another workflow folder to an existing named package."
      mainClassName="overflow-y-auto"
      actions={
        result && createdWorkflowNames.length === 1 ? (
          <Button type="button" size="sm" onClick={() => void handleZipDownload()}>
            <Download className="size-3.5" />
            Download ZIP
          </Button>
        ) : null
      }
    >
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
        <Card className="border-white/8 bg-white/[0.035] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Skill/Workflow Source Mode</CardTitle>
            <CardDescription className="text-zinc-500">
              Use one mode at a time: merge multiple workflows into one package, or append a workflow incrementally into an existing package.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                type="button"
                variant={packageMode === 'merge' ? 'default' : 'outline'}
                onClick={() => {
                  setPackageMode('merge')
                  setBundleNameInput('')
                  setSelectedBundleName('')
                  setSelectedSkillIds([])
                  setAppendStagedSkillId(null)
                  setWorkflowLoadErrors({})
                  setWorkflowPickResetKey((k) => k + 1)
                  setResult(null)
                }}
              >
                Build workflow folders
              </Button>
              <Button
                type="button"
                variant={packageMode === 'append' ? 'default' : 'outline'}
                onClick={() => {
                  setPackageMode('append')
                  setBundleNameInput('')
                  setSelectedBundleName('')
                  setSelectedSkillIds([])
                  setAppendStagedSkillId(null)
                  setWorkflowLoadErrors({})
                  setWorkflowPickResetKey((k) => k + 1)
                  setResult(null)
                  setCreatedWorkflowNames([])
                }}
              >
                Add workflow to existing bundle
              </Button>
            </div>

            {packageMode === 'merge' ? (
              <div className="space-y-2">
                <p className="text-xs text-zinc-400">Skill package folder name (required)</p>
                <Input
                  value={bundleNameInput}
                  onChange={(event) => setBundleNameInput(event.target.value)}
                  placeholder="e.g. acme_customer_ops — creates output/skill_package/<name>/…"
                  className="border-white/15 bg-black/40 text-zinc-100 placeholder:text-zinc-500"
                />
              </div>
            ) : null}

            <div className="rounded-xl border border-white/10 bg-black/20 p-4">
              {skillsQ.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-9 w-full rounded-lg bg-white/10" />
                  <Skeleton className="h-9 w-full rounded-lg bg-white/10" />
                  <Skeleton className="h-9 w-full rounded-lg bg-white/10" />
                </div>
              ) : skillsQ.isError ? (
                <p className="text-sm text-red-300">{errorMessage(skillsQ.error, 'Could not load skills.')}</p>
              ) : sortedSkills.length === 0 ? (
                <p className="text-sm text-zinc-500">No saved skills yet. Create one in Human Edit first, then return here.</p>
              ) : (
                <div className="space-y-3">
                  {packageMode === 'append' ? (
                    <div className="space-y-2">
                      <p className="text-xs text-zinc-400">Target existing skill package bundle</p>
                      {packagesQ.isLoading ? (
                        <Skeleton className="h-9 w-full rounded-lg bg-white/10" />
                      ) : packagesQ.isError ? (
                        <p className="text-xs text-red-300">{errorMessage(packagesQ.error, 'Could not load packages.')}</p>
                      ) : sortedPackages.length === 0 ? (
                        <p className="text-xs text-zinc-500">No saved packages yet. Generate one first, then append workflows to it.</p>
                      ) : (
                        <Select
                          value={selectedBundleName || NO_PACKAGE_SENTINEL}
                          onValueChange={(value) => {
                            if (value === NO_PACKAGE_SENTINEL) {
                              setSelectedBundleName('')
                              setSelectedSkillIds([])
                              setAppendStagedSkillId(null)
                              setWorkflowLoadErrors({})
                              return
                            }
                            loadSelectedBundle(value)
                          }}
                        >
                          <SelectTrigger size="sm" className="w-full border-white/15 bg-black/40 text-zinc-100">
                            <SelectValue placeholder="Select a skill package...">
                              {appendTargetPackage ? <AppendPackageTriggerValue pkg={appendTargetPackage} /> : undefined}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={NO_PACKAGE_SENTINEL} className="text-zinc-500">
                              Select a skill package bundle…
                            </SelectItem>
                            {sortedPackages.map((pkg) => (
                              <SelectItem key={pkg.package_name} value={pkg.package_name} className="pr-8">
                                <div className="flex w-full min-w-0 items-start justify-between gap-2">
                                  <div className="min-w-0 flex flex-col gap-0.5">
                                    <span className="truncate font-medium">{pkg.package_name}</span>
                                    <span className="truncate font-mono text-[11px] text-zinc-500">
                                      skill_package/{pkg.package_name}
                                    </span>
                                    <span className="truncate text-[11px] text-zinc-500">{bundleSummaryLine(pkg)}</span>
                                  </div>
                                  <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                                    {pkg.workflows.reduce((acc, wf) => acc + wf.files.length, 0)} files
                                  </span>
                                </div>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  ) : null}

                  <p className="text-xs text-zinc-400">
                    {packageMode === 'merge' ? 'Source workflows for bundle generation' : 'Workflow/skill to add'}
                  </p>
                  {packageMode === 'merge' ? (
                    <Select
                      key={`workflow-picker-merge-${workflowPickResetKey}`}
                      onValueChange={(skillId) => {
                        setWorkflowPickResetKey((k) => k + 1)
                        void mergeSkillSelection(skillId)
                      }}
                      disabled={availableSkillsToAdd.length === 0}
                    >
                      <SelectTrigger size="sm" className="w-full border-white/15 bg-black/40 text-zinc-100">
                        <SelectValue placeholder="Choose a saved workflow (adds to list below)" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableSkillsToAdd.map((skill) => (
                          <SelectItem key={skill.skill_id} value={skill.skill_id}>
                            <span className="truncate">{skill.title}</span>
                            <span className="ml-2 shrink-0 text-xs text-zinc-500">{skill.step_count} steps</span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Select
                      key={`workflow-picker-append-${workflowPickResetKey}-${selectedBundleName ?? 'none'}`}
                      value={appendStagedSkillId ?? NO_APPEND_WORKFLOW_SENTINEL}
                      onValueChange={(skillId) => {
                        setAppendStagedSkillId(skillId === NO_APPEND_WORKFLOW_SENTINEL ? null : skillId)
                      }}
                      disabled={availableSkillsToAdd.length === 0 || !selectedBundleName || isAppending}
                    >
                      <SelectTrigger size="sm" className="w-full border-white/15 bg-black/40 text-zinc-100">
                        <SelectValue
                          placeholder={
                            selectedBundleName ? 'Choose a workflow, then append below' : 'Pick a bundle above first'
                          }
                        />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_APPEND_WORKFLOW_SENTINEL} className="text-zinc-500">
                          None selected
                        </SelectItem>
                        {availableSkillsToAdd.map((skill) => (
                          <SelectItem key={skill.skill_id} value={skill.skill_id}>
                            <span className="truncate">{skill.title}</span>
                            <span className="ml-2 shrink-0 text-xs text-zinc-500">{skill.step_count} steps</span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  <p className="text-xs text-zinc-500">
                    {packageMode === 'merge'
                      ? 'Each pick adds another workflow folder; the dropdown resets each time — see “Selected workflows” below.'
                      : 'Choosing a workflow only stages it — click “Append workflow to bundle” to write to disk.'}
                  </p>
                </div>
              )}
            </div>

            {selectedSkillIds.length > 0 && (
              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                <p className="text-xs font-medium text-zinc-400 mb-2">
                  {packageMode === 'merge' ? 'Selected workflows' : 'Added skills'} ({selectedSkillIds.length}):
                </p>
                <div className="flex flex-wrap gap-2">
                  {selectedSkillIds.map((skillId) => {
                    const skill = sortedSkills.find((s) => s.skill_id === skillId)
                    return (
                      <Badge
                        key={skillId}
                        variant="outline"
                        className="border-white/15 bg-white/[0.08] text-zinc-200 px-2.5 py-1"
                      >
                        <span className="truncate">{skill?.title}</span>
                        {packageMode === 'merge' ? (
                          <button
                            type="button"
                            onClick={() => removeSkillSelection(skillId)}
                            className="ml-1.5 hover:text-white transition-colors"
                          >
                            <X className="size-3" />
                          </button>
                        ) : null}
                      </Badge>
                    )
                  })}
                </div>
              </div>
            )}

            {Object.keys(workflowLoadErrors).length > 0 ? (
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                {Object.entries(workflowLoadErrors).map(([skillId, message]) => {
                  const skill = sortedSkills.find((s) => s.skill_id === skillId)
                  return (
                    <p key={skillId} className="text-xs text-red-300">
                      {skill?.title ?? skillId}: {message}
                    </p>
                  )
                })}
              </div>
            ) : null}

            <div className="space-y-4 border-t border-white/10 pt-4">
              {packageMode === 'append' ? (
                <p className="text-xs text-zinc-500">
                  Add-to-bundle writes to{' '}
                  <span className="font-mono text-zinc-400">
                    output/skill_package/&lt;your bundle&gt;/workflows/&lt;folder&gt;/</span>{' '}
                  when you append — stage a workflow above, then use the button. No JSON paste.
                </p>
              ) : null}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap gap-2">
                  {result ? (
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      {result.stepCount} steps
                    </Badge>
                  ) : null}
                  {createdWorkflowNames.length > 0 ? (
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      {createdWorkflowNames.length} workflow{createdWorkflowNames.length === 1 ? '' : 's'} ready
                    </Badge>
                  ) : null}
                </div>
                <Button
                  type="button"
                  className="shrink-0"
                  onClick={() => void handleGenerate()}
                  disabled={
                    isGenerating ||
                    isAppending ||
                    (packageMode === 'merge' &&
                      (selectedSkillIds.length === 0 || !bundleNameInput.trim())) ||
                    (packageMode === 'append' && (!selectedBundleName || !appendStagedSkillId))
                  }
                >
                  {isGenerating || isAppending ? (
                    <LoaderCircle className="size-3.5 animate-spin" />
                  ) : (
                    <Package className="size-3.5" />
                  )}
                  {packageMode === 'merge'
                    ? selectedSkillIds.length > 0
                      ? 'Generate Workflow Folders'
                      : 'Generate Workflow Folder'
                    : 'Append workflow to bundle'}
                </Button>
              </div>
              {isBuildBusy ? (
                <div className="rounded-xl border border-sky-400/20 bg-sky-500/[0.07] p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-sky-100">
                        {isAppending ? 'Appending workflow' : 'Generating skill package'}
                      </p>
                      <p className="text-xs text-sky-100/75">{generationStatusLabel}</p>
                    </div>
                    <Badge variant="outline" className="border-sky-300/20 bg-sky-300/10 text-sky-100">
                      {generationProgressValue}%
                    </Badge>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-linear-to-r from-sky-400 via-cyan-300 to-emerald-300 transition-[width] duration-300 ease-out"
                      style={{ width: `${generationProgressValue}%` }}
                    />
                  </div>
                  <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-sky-100/60">{generationCaption}</p>
                </div>
              ) : null}
              {isBuildBusy || terminalLines.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">Build log</p>
                  <div
                    ref={terminalRef}
                    className="max-h-72 overflow-y-auto rounded-lg border border-zinc-700/50 bg-black/55 px-3 py-2 font-mono text-[11px] leading-relaxed text-emerald-100/95 shadow-inner"
                  >
                    {terminalLines.length === 0 ? (
                      <span className="text-zinc-500">Waiting for server events…</span>
                    ) : (
                      terminalLines.map((line, i) => (
                        <div key={i} className="whitespace-pre-wrap break-all">
                          {line}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>

        {error ? (
          <Card className="border-red-500/20 bg-red-500/5 shadow-none">
            <CardContent className="p-4 text-sm text-red-200">{error}</CardContent>
          </Card>
        ) : null}

        {result ? (
          <Card className="border-emerald-500/20 bg-emerald-500/5 shadow-none">
            <CardContent className="space-y-2 p-4 text-sm text-emerald-100">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-4" />
                {createdWorkflowNames.length > 1
                  ? `Saved ${createdWorkflowNames.length} workflows under output/skill_package/${result.bundleSlug}/workflows/.`
                  : `Saved under output/skill_package/${result.bundleSlug}/workflows/${result.name}.`}
              </div>
              {createdWorkflowNames.length > 0 ? (
                <p className="text-xs text-emerald-200/85">Workflows: {createdWorkflowNames.join(', ')}</p>
              ) : null}
              {result.warnings.map((warning) => (
                <p key={warning} className="text-xs text-emerald-200/85">
                  {warning}
                </p>
              ))}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </AppShell>
  )
}
