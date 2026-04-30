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
import { GripVertical, Trash2 } from 'lucide-react'

type Props = {
  steps: StepEditorDTO[]
  version: number
  onReorder: (newOrder: number[]) => void
  onDelete: (index: number) => void
}

function compactStepLabel(label: string): string {
  return label.replace(/^Step\s+\d+:\s*/i, '').trim()
}

export function WorkflowViewer({ steps, version, onReorder, onDelete }: Props) {
  const selected = useEditorStore((s) => s.selectedStepIndex)
  const dirty = useEditorStore((s) => s.dirtySteps)
  const setSel = useEditorStore((s) => s.setSelectedStepIndex)
  const [deleteIndex, setDeleteIndex] = useState<number | null>(null)
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null)

  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length || from === to) return
    const order = steps.map((_, i) => i)
    const [moved] = order.splice(from, 1)
    order.splice(to, 0, moved)
    onReorder(order)
  }

  return (
    <>
      <aside className="border-border bg-card/35 supports-[backdrop-filter]:bg-card/25 relative z-10 flex min-h-0 min-w-0 flex-col border-b backdrop-blur-[2px] md:border-r md:border-b-0">
        <div className="border-border/80 space-y-0.5 border-b bg-muted/5 p-3">
          <h2 className="text-foreground text-sm font-semibold tracking-tight">Workflow</h2>
          <p className="text-muted-foreground text-xs">Version {version}</p>
        </div>
        <ScrollArea className="min-h-[12rem] w-full flex-1 md:min-h-0">
          <ol className="w-full space-y-1.5 p-2">
            {steps.map((st) => (
              <li
                key={st.id}
                className="w-full space-y-1.5"
                draggable
                onDragStart={() => setDraggingIndex(st.step_index)}
                onDragOver={(event) => {
                  event.preventDefault()
                }}
                onDrop={() => {
                  if (draggingIndex === null) return
                  move(draggingIndex, st.step_index)
                  setDraggingIndex(null)
                }}
                onDragEnd={() => setDraggingIndex(null)}
              >
                <button
                  type="button"
                  onClick={() => setSel(st.step_index)}
                  className={cn(
                    'border-border bg-background hover:bg-muted/50 flex w-full min-w-0 items-start gap-2 rounded-lg border p-2.5 text-left text-sm transition-colors',
                    'focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none',
                    selected === st.step_index && 'ring-ring border-primary/50 bg-primary/5 ring-1',
                    draggingIndex === st.step_index && 'opacity-70',
                  )}
                >
                  <span className="text-muted-foreground mt-0.5 shrink-0" aria-hidden>
                    <GripVertical className="size-4" />
                  </span>
                  <span
                    className="bg-muted text-muted-foreground flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs font-medium"
                    aria-hidden
                  >
                    {st.step_index + 1}
                  </span>
                  <span className="min-w-0 flex-1 whitespace-normal [overflow-wrap:anywhere]">
                    {compactStepLabel(st.human_readable_description)}
                  </span>
                  <span className="flex shrink-0 items-start gap-1">
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
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive -mr-1 h-7 w-7"
                      title="Remove step"
                      onClick={(event) => {
                        event.stopPropagation()
                        setDeleteIndex(st.step_index)
                      }}
                      aria-label="Remove step"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </span>
                </button>
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
