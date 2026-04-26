import { useState } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { StepEditorDTO } from '../types/workflow'
import { useEditorStore } from '../store/editorStore'
import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react'

type Props = {
  steps: StepEditorDTO[]
  version: number
  onReorder: (newOrder: number[]) => void
  onDelete: (index: number) => void
}

export function WorkflowViewer({ steps, version, onReorder, onDelete }: Props) {
  const selected = useEditorStore((s) => s.selectedStepIndex)
  const dirty = useEditorStore((s) => s.dirtySteps)
  const setSel = useEditorStore((s) => s.setSelectedStepIndex)
  const [deleteIndex, setDeleteIndex] = useState<number | null>(null)

  const move = (from: number, delta: number) => {
    const to = from + delta
    if (to < 0 || to >= steps.length) return
    const order = steps.map((_, i) => i)
    const t = order[to]
    order[to] = order[from]
    order[from] = t
    onReorder(order)
  }

  return (
    <>
      <aside className="border-border bg-card/30 flex min-h-0 min-w-0 flex-col border-b md:w-auto md:max-w-sm md:border-r md:border-b-0">
        <div className="border-border space-y-0.5 border-b p-3">
          <h2 className="text-foreground text-sm font-semibold tracking-tight">Workflow</h2>
          <p className="text-muted-foreground text-xs">Version {version}</p>
        </div>
        <ScrollArea className="min-h-[12rem] flex-1 md:min-h-0">
          <ol className="space-y-1.5 p-2 pr-3">
            {steps.map((st) => (
              <li key={st.id} className="space-y-1.5">
                <button
                  type="button"
                  onClick={() => setSel(st.step_index)}
                  className={cn(
                    'border-border bg-background hover:bg-muted/50 flex w-full min-w-0 items-start gap-2 rounded-lg border p-2.5 text-left text-sm transition-colors',
                    'focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none',
                    selected === st.step_index && 'ring-ring border-primary/50 bg-primary/5 ring-1',
                  )}
                >
                  <span
                    className="bg-muted text-muted-foreground flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs font-medium"
                    aria-hidden
                  >
                    {st.step_index + 1}
                  </span>
                  <span className="min-w-0 flex-1 break-words">{st.human_readable_description}</span>
                  <span className="flex shrink-0 flex-col items-end gap-0.5">
                    {dirty.has(st.step_index) ? (
                      <Badge variant="secondary" className="text-[0.65rem]">
                        edited
                      </Badge>
                    ) : null}
                    {st.flags.is_destructive ? (
                      <Badge variant="destructive" className="text-[0.65rem]">
                        destructive
                      </Badge>
                    ) : null}
                    {st.flags.generic_intent ? (
                      <Badge variant="outline" className="text-[0.65rem]">
                        intent
                      </Badge>
                    ) : null}
                  </span>
                </button>
                <div className="text-muted-foreground flex items-center gap-0.5 pl-1">
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    className="h-7 w-7"
                    title="Move up"
                    disabled={st.step_index === 0}
                    onClick={() => move(st.step_index, -1)}
                    aria-label="Move step up"
                  >
                    <ChevronUp className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    className="h-7 w-7"
                    title="Move down"
                    disabled={st.step_index >= steps.length - 1}
                    onClick={() => move(st.step_index, 1)}
                    aria-label="Move step down"
                  >
                    <ChevronDown className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive h-7 w-7"
                    title="Remove step"
                    onClick={() => setDeleteIndex(st.step_index)}
                    aria-label="Remove step"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </li>
            ))}
          </ol>
        </ScrollArea>
      </aside>

      <AlertDialog open={deleteIndex !== null} onOpenChange={(o) => !o && setDeleteIndex(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove step {deleteIndex !== null ? deleteIndex + 1 : ''}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the step from the skill package. You can recompile from session if the recording data is
              still available.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (deleteIndex === null) return
                onDelete(deleteIndex)
                setDeleteIndex(null)
              }}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
