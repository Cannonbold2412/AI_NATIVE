import { useMemo, useRef, useState, type DragEvent } from 'react'
import { toast } from 'sonner'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { buildSkillPackage, downloadSkillPackZip, downloadTextAsset, parseInputs, type SkillPackBuildResult } from '@/services/skillPackBuilder'
import { CheckCircle2, Copy, Download, FileJson, FileText, LoaderCircle, Package, UploadCloud } from 'lucide-react'
import { cn } from '@/lib/utils'

const TAB_OPTIONS = [
  { key: 'skill.md', label: 'skill.md', icon: FileText },
  { key: 'skill.json', label: 'skill.json', icon: FileJson },
  { key: 'inputs.json', label: 'inputs.json', icon: FileJson },
  { key: 'manifest.json', label: 'manifest.json', icon: FileJson },
] as const

type OutputTabKey = (typeof TAB_OPTIONS)[number]['key']

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`))
    reader.readAsText(file)
  })
}

function tabContent(result: SkillPackBuildResult, tab: OutputTabKey): string {
  if (tab === 'skill.md') return result.skillMd
  if (tab === 'skill.json') return result.skillJson
  if (tab === 'inputs.json') return result.inputJson
  return result.manifestJson
}

export function SkillPackBuilderPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [jsonText, setJsonText] = useState('')
  const [selectedFile, setSelectedFile] = useState('')
  const [activeTab, setActiveTab] = useState<OutputTabKey>('skill.md')
  const [dragActive, setDragActive] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SkillPackBuildResult | null>(null)

  const detectedInputs = useMemo(() => {
    if (!jsonText.trim()) return []
    try {
      return parseInputs(jsonText)
    } catch {
      return []
    }
  }, [jsonText])

  async function loadFile(file: File) {
    const text = await readFileAsText(file)
    setJsonText(text)
    setSelectedFile(file.name)
    setError(null)
  }

  async function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      await loadFile(file)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not load file.'
      setError(message)
      toast.error(message)
    } finally {
      event.target.value = ''
    }
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragActive(true)
  }

  function onDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragActive(false)
  }

  async function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragActive(false)
    const file = event.dataTransfer.files?.[0]
    if (!file) return
    try {
      await loadFile(file)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not load file.'
      setError(message)
      toast.error(message)
    }
  }

  async function handleGenerate() {
    setIsLoading(true)
    setError(null)
    try {
      const next = await buildSkillPackage(jsonText)
      setResult(next)
      setActiveTab('skill.md')
      toast.success(next.usedLlm ? 'Skill Package generated and saved.' : 'Skill Package generated, saved, and completed with deterministic fallback.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not generate Skill Package.'
      setError(message)
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  async function handleCopy(tab: OutputTabKey) {
    if (!result) return
    try {
      await navigator.clipboard.writeText(tabContent(result, tab))
      toast.success(`${tab} copied`)
    } catch {
      toast.error(`Could not copy ${tab}`)
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
      description="Upload or paste a compiled workflow JSON, then generate and save a package folder with skill.md, skill.json, inputs.json, and manifest.json."
      mainClassName="overflow-y-auto"
      actions={
        result ? (
          <Button type="button" size="sm" onClick={() => void handleZipDownload()}>
            <Download className="size-3.5" />
            Download ZIP
          </Button>
        ) : null
      }
    >
      <div className="mx-auto grid w-full max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] sm:px-6">
        <div className="space-y-6">
          <Card className="border-white/8 bg-white/[0.035] shadow-none">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="text-white">Source JSON</CardTitle>
              <CardDescription className="text-zinc-500">
                Upload a `skill.json` file or paste the workflow payload directly. Each generation is saved as its own package folder.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div
                role="button"
                tabIndex={0}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={(event) => void onDrop(event)}
                className={cn(
                  'rounded-xl border border-dashed px-4 py-8 text-center transition-colors',
                  dragActive
                    ? 'border-sky-400/60 bg-sky-500/10 text-sky-100'
                    : 'border-white/10 bg-black/20 text-zinc-400 hover:border-white/20 hover:text-zinc-200',
                )}
              >
                <UploadCloud className="mx-auto size-8" />
                <p className="mt-3 text-sm font-medium">{selectedFile || 'Drag and drop a .json file here'}</p>
                <p className="mt-1 text-xs text-zinc-500">or click to choose a local file</p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(event) => void onFileChange(event)}
              />
              <Textarea
                value={jsonText}
                onChange={(event) => {
                  setJsonText(event.target.value)
                  setError(null)
                }}
                placeholder='Paste workflow JSON here, for example: {"skills":[{"steps":[...]}]}'
                className="min-h-[22rem] resize-y border-white/10 bg-black/20 font-mono text-xs leading-6 text-zinc-100 placeholder:text-zinc-500"
              />
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                    {detectedInputs.length} inputs detected
                  </Badge>
                  {result ? (
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      {result.stepCount} steps
                    </Badge>
                  ) : null}
                </div>
                <Button type="button" onClick={() => void handleGenerate()} disabled={isLoading}>
                  {isLoading ? <LoaderCircle className="size-3.5 animate-spin" /> : <Package className="size-3.5" />}
                  Generate Skill Package
                </Button>
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
                  Skill Package ready and saved to the packages library.
                </div>
                {result.warnings.map((warning) => (
                  <p key={warning} className="text-xs text-emerald-200/85">
                    {warning}
                  </p>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </div>

        <Card className="border-white/8 bg-white/[0.035] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Package Output</CardTitle>
            <CardDescription className="text-zinc-500">
              Review the saved package artifacts, copy them, or download each file separately.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            {result ? (
              <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as OutputTabKey)}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <TabsList variant="line" className="bg-transparent p-0">
                    {TAB_OPTIONS.map((tab) => {
                      const Icon = tab.icon
                      return (
                        <TabsTrigger
                          key={tab.key}
                          value={tab.key}
                          className="rounded-lg border border-white/10 bg-white/[0.03] px-3 text-zinc-300 data-active:bg-white/[0.08] data-active:text-white"
                        >
                          <Icon className="size-3.5" />
                          {tab.label}
                        </TabsTrigger>
                      )
                    })}
                  </TabsList>
                  <div className="flex items-center gap-2">
                    <Button type="button" size="sm" variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-200" onClick={() => void handleCopy(activeTab)}>
                      <Copy className="size-3.5" />
                      Copy
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-white/10 bg-white/[0.04] text-zinc-200"
                      onClick={() =>
                        downloadTextAsset(
                          activeTab,
                          tabContent(result, activeTab),
                          activeTab.endsWith('.json') ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8',
                        )
                      }
                    >
                      <Download className="size-3.5" />
                      Download
                    </Button>
                  </div>
                </div>

                {TAB_OPTIONS.map((tab) => (
                  <TabsContent key={tab.key} value={tab.key} className="mt-4">
                    <Textarea
                      readOnly
                      value={tabContent(result, tab.key)}
                      className="min-h-[42rem] resize-none border-white/10 bg-black/25 font-mono text-xs leading-6 text-zinc-100"
                    />
                  </TabsContent>
                ))}
              </Tabs>
            ) : (
              <div className="flex min-h-[34rem] items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/15 px-6 text-center text-sm text-zinc-500">
                Generate a package to view `skill.md`, `skill.json`, `inputs.json`, and `manifest.json`.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
