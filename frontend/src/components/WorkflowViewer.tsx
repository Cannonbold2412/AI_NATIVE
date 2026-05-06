import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
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
import { RECORDING_DRAG_MODE_CLEAR_VISUAL, RECORDING_SCREENSHOT_DRAG_MIME } from '@/api/workflowApi'
import { BoxSelect, ChevronDown, GripVertical, Info, Plus, Trash2 } from 'lucide-react'

const ADD_ACTION_OPTIONS = [
  { value: 'click', label: 'Click' },
  { value: 'fill', label: 'Fill' },
  { value: 'navigate', label: 'Navigate' },
  { value: 'scroll', label: 'Scroll' },
  { value: 'check', label: 'Check' },
] as const

type AddActionKind = (typeof ADD_ACTION_OPTIONS)[number]['value']

type Props = {
  steps: StepEditorDTO[]
  version: number
  onReorder: (newOrder: number[]) => void
  onDelete: (index: number) => void
  onAddAction: (actionKind: AddActionKind) => void
  /** Drop a recording screenshot (custom drag payload) onto a step to swap visuals and refresh anchors. */
  onDroppedRecordingScreenshot?: (stepIndex: number, eventIndex: number) => void
  /** Drop “No image” payload to detach screenshot and clear anchors. */
  onClearStepVisual?: (stepIndex: number) => void
  recordingShotDragActive?: boolean
}

function compactStepLabel(label: string): string {
  return label.replace(/^Step\s+\d+:\s*/i, '').trim()
}

function visualBboxState(step: StepEditorDTO): {
  usable: boolean
  label: string
  title: string
} | null {
  if (step.flags.is_scroll) return null
  const bbox = step.screenshot.bbox || {}
  const x = Number(bbox.x ?? 0)
  const y = Number(bbox.y ?? 0)
  const w = Number(bbox.w ?? 0)
  const h = Number(bbox.h ?? 0)
  if (w >= 2 && h >= 2) {
    return {
      usable: true,
      label: `${Math.round(w)}x${Math.round(h)}`,
      title: `Visual bbox saved: x ${Math.round(x)}, y ${Math.round(y)}, w ${Math.round(w)}, h ${Math.round(h)}`,
    }
  }
  return {
    usable: false,
    label: 'missing',
    title: 'No usable visual bbox saved for this action.',
  }
}

type WorkflowHeaderProps = {
  version: number
  onAddAction: (actionKind: AddActionKind) => void
}

function WorkflowHeader({ version, onAddAction }: WorkflowHeaderProps) {
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const addMenuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!addMenuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (addMenuRef.current?.contains(event.target as Node)) return
      setAddMenuOpen(false)
    }
    window.addEventListener('pointerdown', onPointerDown)
    return () => window.removeEventListener('pointerdown', onPointerDown)
  }, [addMenuOpen])

  return (
    <div className="border-border/80 space-y-2 border-b bg-muted/5 p-3">
      <div className="flex items-center gap-1.5">
        <h2 className="text-foreground text-sm font-semibold tracking-tight">Workflow</h2>
        <span
          className="text-muted-foreground hover:text-foreground/80 inline-flex shrink-0"
          title="Drag steps to reorder. From Tools → Recording screenshots: drag a frame or No image onto a step to swap/clear screenshots and anchors."
        >
          <Info className="size-3.5" aria-hidden />
          <span className="sr-only">Workflow tips</span>
        </span>
      </div>
      <div className="flex items-center gap-2">
        <p className="text-muted-foreground min-w-0 flex-1 text-xs">Version {version}</p>
        <div ref={addMenuRef} className="relative shrink-0">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 px-2.5 text-xs"
            title="Add action after the selected step"
            aria-haspopup="menu"
            aria-expanded={addMenuOpen}
            onClick={() => setAddMenuOpen((open) => !open)}
          >
            <Plus className="size-3.5" />
            Add
            <ChevronDown className="size-3.5" />
          </Button>
          {addMenuOpen ? (
            <div
              role="menu"
              className="border-border bg-popover text-popover-foreground absolute right-0 top-full z-30 mt-1 w-36 overflow-hidden rounded-md border p-1 shadow-lg"
            >
              {ADD_ACTION_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="menuitem"
                  className="hover:bg-muted focus-visible:bg-muted flex h-8 w-full items-center rounded-sm px-2 text-left text-xs outline-none"
                  onClick={() => {
                    setAddMenuOpen(false)
                    onAddAction(option.value)
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

type WorkflowStepItemProps = {
  step: StepEditorDTO
  isSelected: boolean
  isDirty: boolean
  isDragging: boolean
  recordingShotDragActive?: boolean
  draggingIndex: number | null
  onSelect: (index: number) => void
  onDeleteRequest: (index: number) => void
  onDragStart: (index: number) => void
  onDragEnd: () => void
  onMove: (from: number, to: number) => void
  onDroppedRecordingScreenshot?: (stepIndex: number, eventIndex: number) => void
  onClearStepVisual?: (stepIndex: number) => void
}

function WorkflowStepItem({
  step,
  isSelected,
  isDirty,
  isDragging,
  recordingShotDragActive,
  draggingIndex,
  onSelect,
  onDeleteRequest,
  onDragStart,
  onDragEnd,
  onMove,
  onDroppedRecordingScreenshot,
  onClearStepVisual,
}: WorkflowStepItemProps) {
  const bboxState = visualBboxState(step)

  const selectStep = () => onSelect(step.step_index)
  const onRowKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    selectStep()
  }

  const onDragOver = (event: DragEvent<HTMLLIElement>) => {
    event.preventDefault()
    event.dataTransfer.dropEffect =
      recordingShotDragActive || event.dataTransfer.types.includes(RECORDING_SCREENSHOT_DRAG_MIME) ? 'copy' : 'move'
  }

  const onDrop = (event: DragEvent<HTMLLIElement>) => {
    event.preventDefault()
    const raw = event.dataTransfer.getData(RECORDING_SCREENSHOT_DRAG_MIME).trim()
    if (raw && (onClearStepVisual || onDroppedRecordingScreenshot)) {
      handleRecordingScreenshotDrop(raw, step.step_index, onDroppedRecordingScreenshot, onClearStepVisual)
      return
    }
    if (draggingIndex === null) return
    onMove(draggingIndex, step.step_index)
    onDragEnd()
  }

  return (
    <li
      className="w-full space-y-1.5"
      draggable
      onDragStart={() => onDragStart(step.step_index)}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={selectStep}
        onKeyDown={onRowKeyDown}
        className={cn(
          'border-border bg-background hover:bg-muted/50 flex w-full min-w-0 items-start gap-2 rounded-lg border p-2.5 text-left text-sm transition-colors',
          'focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none',
          isSelected && 'ring-ring border-primary/50 bg-primary/5 ring-1',
          isDragging && 'opacity-70',
        )}
      >
        <span className="text-muted-foreground mt-0.5 shrink-0" aria-hidden>
          <GripVertical className="size-4" />
        </span>
        <span
          className="bg-muted text-muted-foreground flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs font-medium"
          aria-hidden
        >
          {step.step_index + 1}
        </span>
        <span className="min-w-0 flex-1 whitespace-normal [overflow-wrap:anywhere]">
          <span className="block">{compactStepLabel(step.human_readable_description)}</span>
          {bboxState ? <VisualBboxBadge state={bboxState} /> : null}
        </span>
        <StepBadges step={step} isDirty={isDirty} onDeleteRequest={onDeleteRequest} />
      </div>
    </li>
  )
}

function handleRecordingScreenshotDrop(
  raw: string,
  stepIndex: number,
  onDroppedRecordingScreenshot?: (stepIndex: number, eventIndex: number) => void,
  onClearStepVisual?: (stepIndex: number) => void,
) {
  try {
    const parsed = JSON.parse(raw) as { event_index?: unknown; mode?: unknown }
    if (parsed.mode === RECORDING_DRAG_MODE_CLEAR_VISUAL && onClearStepVisual) {
      void onClearStepVisual(stepIndex)
      return
    }
    const eventIndex = parsed.event_index
    if (typeof eventIndex === 'number' && Number.isFinite(eventIndex) && eventIndex >= 0) {
      void onDroppedRecordingScreenshot?.(stepIndex, Math.floor(eventIndex))
    }
  } catch {
    // Ignore malformed drag payloads from unrelated sources.
  }
}

type BboxState = NonNullable<ReturnType<typeof visualBboxState>>

function VisualBboxBadge({ state }: { state: BboxState }) {
  return (
    <span
      className={cn(
        'mt-1 inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-0.5 text-[0.65rem] leading-none',
        state.usable ? 'border-sky-400/25 bg-sky-400/10 text-sky-300' : 'border-white/10 bg-white/[0.03] text-zinc-500',
      )}
      title={state.title}
    >
      <BoxSelect className="size-3 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">bbox {state.label}</span>
    </span>
  )
}

function StepBadges({
  step,
  isDirty,
  onDeleteRequest,
}: {
  step: StepEditorDTO
  isDirty: boolean
  onDeleteRequest: (index: number) => void
}) {
  return (
    <span className="flex shrink-0 items-start gap-1">
      {isDirty ? (
        <Badge variant="secondary" className="text-[0.65rem]">
          edited
        </Badge>
      ) : null}
      {step.flags.is_destructive ? (
        <Badge variant="destructive" className="text-[0.65rem]">
          destructive
        </Badge>
      ) : null}
      {step.flags.generic_intent ? (
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
          onDeleteRequest(step.step_index)
        }}
        aria-label="Remove step"
      >
        <Trash2 className="size-3.5" />
      </Button>
    </span>
  )
}

type DeleteStepDialogProps = {
  deleteIndex: number | null
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

function DeleteStepDialog({ deleteIndex, onOpenChange, onConfirm }: DeleteStepDialogProps) {
  return (
    <AlertDialog open={deleteIndex !== null} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Remove step {deleteIndex !== null ? deleteIndex + 1 : ''}?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the step from the skill package. You can recompile from session if the recording data is still
            available.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onConfirm}>
            Remove
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function WorkflowViewer({
  steps,
  version,
  onReorder,
  onDelete,
  onAddAction,
  onDroppedRecordingScreenshot,
  onClearStepVisual,
  recordingShotDragActive,
}: Props) {
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
        <WorkflowHeader version={version} onAddAction={onAddAction} />
        <ScrollArea className="min-h-[12rem] w-full flex-1 md:min-h-0">
          <ol className="w-full space-y-1.5 p-2">
            {steps.map((step) => (
              <WorkflowStepItem
                key={step.id}
                step={step}
                isSelected={selected === step.step_index}
                isDirty={dirty.has(step.step_index)}
                isDragging={draggingIndex === step.step_index}
                recordingShotDragActive={recordingShotDragActive}
                draggingIndex={draggingIndex}
                onSelect={setSel}
                onDeleteRequest={setDeleteIndex}
                onDragStart={setDraggingIndex}
                onDragEnd={() => setDraggingIndex(null)}
                onMove={move}
                onDroppedRecordingScreenshot={onDroppedRecordingScreenshot}
                onClearStepVisual={onClearStepVisual}
              />
            ))}
          </ol>
        </ScrollArea>
      </aside>

      <DeleteStepDialog
        deleteIndex={deleteIndex}
        onOpenChange={(open) => !open && setDeleteIndex(null)}
        onConfirm={() => {
          if (deleteIndex === null) return
          onDelete(deleteIndex)
          setDeleteIndex(null)
        }}
      />
    </>
  )
}
