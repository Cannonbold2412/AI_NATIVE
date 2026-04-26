import { useState } from 'react'
import type { WorkflowResponse } from '../types/workflow'
import { fetchWorkflow, patchSkillInputs } from '../api/workflowApi'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { fieldTextareaClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'

type Props = {
  open: boolean
  onClose: () => void
  workflow: WorkflowResponse
  onSaved: (w: WorkflowResponse) => void
}

function ParameterizationForm({ workflow, onClose, onSaved }: Omit<Props, 'open'>) {
  const [inputsJson, setInputsJson] = useState(() => JSON.stringify(workflow.inputs, null, 2))
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const save = () => {
    setErr(null)
    let parsed: Record<string, unknown>[]
    try {
      parsed = JSON.parse(inputsJson) as Record<string, unknown>[]
      if (!Array.isArray(parsed)) throw new Error('inputs must be a JSON array')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Invalid JSON')
      return
    }
    setSaving(true)
    patchSkillInputs(workflow.skill_id, { inputs: parsed })
      .then(() => fetchWorkflow(workflow.skill_id))
      .then((w: WorkflowResponse) => {
        onSaved(w)
        onClose()
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setSaving(false))
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-4">
      <textarea
        className={cn(fieldTextareaClass, 'font-mono min-h-64 flex-1 text-xs')}
        value={inputsJson}
        onChange={(e) => setInputsJson(e.target.value)}
        spellCheck={false}
        aria-label="Variable registry JSON"
      />
      {err ? <p className="text-destructive text-sm">{err}</p> : null}
      <div className="mt-auto flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="button" disabled={saving} onClick={save}>
          {saving ? 'Saving…' : 'Save inputs'}
        </Button>
      </div>
    </div>
  )
}

export function ParameterizationDrawer({ open, onClose, workflow, onSaved }: Props) {
  const version = Number((workflow.package_meta as { version?: number } | undefined)?.version ?? 0)
  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="flex w-full min-w-0 flex-col overflow-hidden p-0 sm:max-w-lg" side="right">
        <SheetHeader className="p-4 pb-2 text-left">
          <SheetTitle id="param-drawer-title">Variable registry</SheetTitle>
          <SheetDescription>
            Package-level <code className="bg-muted rounded px-1">inputs</code> (id, label, type, default, options). Use{' '}
            <code className="bg-muted rounded px-1">{'{{id}}'}</code> in step fields; promote flow can be wired to this
            registry.
          </SheetDescription>
        </SheetHeader>
        <ParameterizationForm
          key={`${workflow.skill_id}-v${version}`}
          workflow={workflow}
          onClose={onClose}
          onSaved={onSaved}
        />
      </SheetContent>
    </Sheet>
  )
}
