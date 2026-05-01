import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { BoxSelect, ImageIcon, Minus, Plus, RotateCcw } from 'lucide-react'
import type { StepScreenshotDTO } from '../types/workflow'
import { RECORDING_DRAG_MODE_CLEAR_VISUAL, RECORDING_SCREENSHOT_DRAG_MIME } from '@/api/workflowApi'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Matches ``app/confidence/uncertainty.py`` audit (non-scroll, w or h under 2). */
export function isWeakVisualBbox(bbox: Record<string, unknown>, isScrollStep: boolean): boolean {
  if (isScrollStep) return false
  const w = Number((bbox as Record<string, number>).w ?? 0)
  const h = Number((bbox as Record<string, number>).h ?? 0)
  return w < 2 || h < 2
}

function clientPointToNatural(
  clientX: number,
  clientY: number,
  img: HTMLImageElement,
): { nx: number; ny: number } {
  const r = img.getBoundingClientRect()
  if (r.width <= 0 || r.height <= 0) return { nx: 0, ny: 0 }
  const nx = ((clientX - r.left) / r.width) * img.naturalWidth
  const ny = ((clientY - r.top) / r.height) * img.naturalHeight
  return { nx, ny }
}

function clampRectToImage(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  maxW: number,
  maxH: number,
): { x: number; y: number; w: number; h: number } {
  let x = Math.min(x0, x1)
  let y = Math.min(y0, y1)
  let w = Math.abs(x1 - x0)
  let h = Math.abs(y1 - y0)
  x = Math.max(0, Math.min(x, maxW))
  y = Math.max(0, Math.min(y, maxH))
  w = Math.min(w, maxW - x)
  h = Math.min(h, maxH - y)
  return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) }
}

function rectToPct(
  rect: { x: number; y: number; w: number; h: number },
  naturalW: number,
  naturalH: number,
) {
  if (!naturalW || !naturalH || !rect.w || !rect.h) return null
  return {
    left: `${(rect.x / naturalW) * 100}%`,
    top: `${(rect.y / naturalH) * 100}%`,
    width: `${(rect.w / naturalW) * 100}%`,
    height: `${(rect.h / naturalH) * 100}%`,
  }
}

type InnerProps = {
  src: string
  bbox: Record<string, unknown>
  dropHighlight?: boolean
  bboxDrawMode?: boolean
  bboxDrawSaving?: boolean
  onCommitDrawnBbox?: (bbox: { x: number; y: number; w: number; h: number }) => void | Promise<void>
  /** When set, show toolbar control to enter/exit draw mode. */
  bboxToolUi?: { active: boolean; onToggle: () => void; saving: boolean } | null
}

function ScreenshotViewInner({
  src,
  bbox,
  dropHighlight,
  bboxDrawMode,
  bboxDrawSaving,
  onCommitDrawnBbox,
  bboxToolUi,
}: InnerProps) {
  const { x = 0, y = 0, w = 0, h = 0 } = bbox as Record<string, number>
  const [zoom, setZoom] = useState(1)
  const [resolvedSrc, setResolvedSrc] = useState(src || '')
  const [fallbackTried, setFallbackTried] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [natural, setNatural] = useState({ w: 0, h: 0 })
  const imgRef = useRef<HTMLImageElement>(null)
  const dragLiveRef = useRef<null | { ax: number; ay: number; cx: number; cy: number }>(null)
  const [drag, setDrag] = useState<null | { ax: number; ay: number; cx: number; cy: number }>(null)

  useEffect(() => {
    dragLiveRef.current = null
    setDrag(null)
  }, [bboxDrawMode, src])

  const overlayPct = useMemo(() => {
    if (!natural.w || !natural.h || !w || !h) return null
    return {
      left: `${(x / natural.w) * 100}%`,
      top: `${(y / natural.h) * 100}%`,
      width: `${(w / natural.w) * 100}%`,
      height: `${(h / natural.h) * 100}%`,
    }
  }, [x, y, w, h, natural.w, natural.h])

  const previewDrawPct = useMemo(() => {
    if (!drag || !natural.w || !natural.h) return null
    const r = clampRectToImage(drag.ax, drag.ay, drag.cx, drag.cy, natural.w, natural.h)
    return rectToPct(r, natural.w, natural.h)
  }, [drag, natural.w, natural.h])

  const finalizeDrawFromPointer = useCallback(
    (e: ReactPointerEvent) => {
      const live = dragLiveRef.current
      dragLiveRef.current = null
      setDrag(null)
      if (
        !live ||
        !onCommitDrawnBbox ||
        !natural.w ||
        !natural.h ||
        !imgRef.current
      ) {
        return
      }
      const pt = clientPointToNatural(e.clientX, e.clientY, imgRef.current)
      const r = clampRectToImage(live.ax, live.ay, pt.nx, pt.ny, natural.w, natural.h)
      const minPx = 4
      if (r.w < minPx || r.h < minPx) return
      void onCommitDrawnBbox(r)
    },
    [natural.w, natural.h, onCommitDrawnBbox],
  )

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!bboxDrawMode || bboxDrawSaving || !imgRef.current || !natural.w) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    const { nx, ny } = clientPointToNatural(e.clientX, e.clientY, imgRef.current)
    const next = { ax: nx, ay: ny, cx: nx, cy: ny }
    dragLiveRef.current = next
    setDrag(next)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!bboxDrawMode || !dragLiveRef.current || !imgRef.current) return
    const { nx, ny } = clientPointToNatural(e.clientX, e.clientY, imgRef.current)
    const next = { ...dragLiveRef.current, cx: nx, cy: ny }
    dragLiveRef.current = next
    setDrag(next)
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!bboxDrawMode || !dragLiveRef.current) return
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* already released */
    }
    finalizeDrawFromPointer(e)
  }

  const onPointerCancel = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragLiveRef.current = null
    setDrag(null)
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* noop */
    }
  }

  return (
    <div
      className={cn(
        'isolate relative overflow-hidden rounded-xl',
        'border border-white/[0.08] bg-black/15',
      )}
    >
      {dropHighlight ? (
        <div
          className="pointer-events-none absolute inset-0 z-[1] rounded-xl bg-sky-400/15 ring-1 ring-sky-400/35 ring-inset backdrop-blur-[0.5px]"
          aria-hidden
        />
      ) : null}
      <div
        className="transition-transform duration-200 ease-out will-change-transform motion-reduce:transition-none motion-reduce:duration-0"
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: 'top center',
        }}
      >
        <div className="bg-muted/15 relative inline-block min-w-0 w-full">
          <div className="shot-wrap relative inline-block min-w-0 max-w-full">
            <img
              ref={imgRef}
              src={resolvedSrc}
              alt="Captured page region for this step"
              className={cn('h-auto w-full max-w-full', bboxDrawMode && !bboxDrawSaving && 'select-none')}
              draggable={false}
              onLoad={(e) => {
                const im = e.currentTarget
                setNatural({ w: im.naturalWidth, h: im.naturalHeight })
                setLoadError('')
              }}
              onError={() => {
                if (!fallbackTried) {
                  setFallbackTried(true)
                  try {
                    const u = new URL(src, window.location.origin)
                    if (u.pathname) {
                      setResolvedSrc(`${u.pathname}${u.search}`)
                      return
                    }
                  } catch {
                    // Keep original error if URL parsing fails.
                  }
                }
                setLoadError('Failed to load screenshot. Try reloading the workflow.')
              }}
            />
            {overlayPct ? (
              <div
                className="ring-primary/40 pointer-events-none absolute z-[2] border-2 border-primary/50"
                style={overlayPct}
                title="Target region (visual match)"
              />
            ) : null}
            {previewDrawPct ? (
              <div
                className="pointer-events-none absolute z-[3] border-2 border-sky-400/90 bg-sky-400/15 shadow-[inset_0_0_0_1px_rgba(56,189,248,0.35)]"
                style={previewDrawPct}
              />
            ) : null}
            {bboxDrawMode ? (
              <div
                role="application"
                aria-label="Draw a rectangle to set the visual bounding box"
                className={cn(
                  'absolute inset-0 z-[4] touch-none',
                  bboxDrawSaving ? 'cursor-wait' : 'cursor-crosshair',
                )}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerCancel}
              />
            ) : null}
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-2 p-2">
        <div className="pointer-events-none flex min-w-0 flex-1 items-start gap-1.5">
          <span
            className="pointer-events-none flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-black/35 text-zinc-300 backdrop-blur-sm"
            title="Screenshot"
            aria-hidden
          >
            <ImageIcon className="size-3.5 shrink-0 opacity-90" strokeWidth={1.75} aria-hidden />
          </span>
          {bboxToolUi ? (
            <div className="pointer-events-auto shrink-0">
              <Button
                type="button"
                size="sm"
                variant={bboxToolUi.active ? 'default' : 'outline'}
                disabled={bboxToolUi.saving}
                className={cn(
                  'h-7 gap-1 border-white/15 bg-black/35 px-2 text-[11px] font-medium backdrop-blur-sm hover:bg-black/45',
                  bboxToolUi.active && 'border-primary/40 bg-primary/25 text-primary-foreground hover:bg-primary/35',
                )}
                title="Draw a rectangle on the screenshot to set signals.visual bbox (CSS pixels)"
                aria-pressed={bboxToolUi.active}
                onClick={() => bboxToolUi.onToggle()}
              >
                <BoxSelect className="size-3.5 shrink-0 opacity-90" strokeWidth={2} aria-hidden />
                Visual bbox
              </Button>
            </div>
          ) : null}
        </div>
        <div
          className="pointer-events-auto ml-auto inline-flex cursor-default items-center gap-px rounded-full border border-white/12 bg-zinc-950/80 py-0.5 pl-0.5 pr-0.5 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-zinc-950/65"
          role="toolbar"
          aria-label="Screenshot zoom"
        >
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="h-7 w-7 cursor-pointer rounded-full text-zinc-300 hover:bg-white/10 hover:text-zinc-50"
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
            aria-label="Zoom out"
          >
            <Minus className="size-3.5" strokeWidth={2} aria-hidden />
          </Button>
          <span className="text-muted-foreground min-w-[2.5rem] text-center font-mono text-[10px] tabular-nums text-zinc-400">
            {Math.round(zoom * 100)}
            <span className="text-zinc-500">%</span>
          </span>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="h-7 w-7 cursor-pointer rounded-full text-zinc-300 hover:bg-white/10 hover:text-zinc-50"
            onClick={() => setZoom((z) => Math.min(3, z + 0.25))}
            aria-label="Zoom in"
          >
            <Plus className="size-3.5" strokeWidth={2} aria-hidden />
          </Button>
          <div className="mx-px h-4 w-px shrink-0 self-center rounded-full bg-white/15" aria-hidden />
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="h-7 w-7 cursor-pointer rounded-full text-zinc-400 hover:bg-white/10 hover:text-zinc-100"
            onClick={() => setZoom(1)}
            aria-label="Reset zoom"
          >
            <RotateCcw className="size-3" strokeWidth={2} aria-hidden />
          </Button>
        </div>
      </div>

      {bboxDrawMode && bboxToolUi ? (
        <p className="text-muted-foreground border-border/60 border-t px-2 py-1.5 text-[11px] leading-snug">
          {bboxToolUi.saving
            ? 'Saving visual bbox…'
            : 'Drag on the image to draw the target region. Release to save (min. a few pixels).'}
        </p>
      ) : null}

      {loadError ? <p className="text-destructive border-border/60 border-t px-2 py-2 text-xs">{loadError}</p> : null}
    </div>
  )
}

export type DropRecordingScreenshotHandlers = {
  stepIndex: number
  recordingShotDragActive?: boolean
  onDroppedRecordingScreenshot?: (stepIndex: number, eventIndex: number) => void | Promise<void>
  onClearStepVisual?: (stepIndex: number) => void | Promise<void>
}

type Props = {
  screenshot: StepScreenshotDTO
  label: string
  /** Non-scroll steps: allow drawing a bbox and PATCH ``signals.visual.bbox``. */
  onSaveVisualBbox?: (bbox: { x: number; y: number; w: number; h: number }) => void | Promise<void>
  isScrollStep?: boolean
} & Partial<DropRecordingScreenshotHandlers>

function recordingDragLikely(dt: DataTransfer | null | undefined, recordingShotDragActive?: boolean): boolean {
  if (!dt) return false
  if (recordingShotDragActive) return true
  return Array.from(dt.types).includes(RECORDING_SCREENSHOT_DRAG_MIME)
}

export function ScreenshotViewer({
  screenshot,
  label,
  stepIndex,
  recordingShotDragActive,
  onDroppedRecordingScreenshot,
  onClearStepVisual,
  onSaveVisualBbox,
  isScrollStep = false,
}: Props) {
  const src = screenshot.full_url || screenshot.element_url || screenshot.scroll_url
  const bbox = screenshot.bbox || {}
  const [optimisticSrc, setOptimisticSrc] = useState<string | null>(null)
  const [optimisticNoImage, setOptimisticNoImage] = useState(false)
  const [bboxDrawActive, setBboxDrawActive] = useState(false)
  const [bboxDrawSaving, setBboxDrawSaving] = useState(false)

  useEffect(() => {
    setOptimisticSrc(null)
    setOptimisticNoImage(false)
  }, [src, stepIndex])

  const effectiveSrc = optimisticNoImage ? '' : optimisticSrc || src || ''
  const effectiveBbox =
    optimisticSrc || optimisticNoImage ? ({} as Record<string, unknown>) : bbox

  useEffect(() => {
    setBboxDrawActive(false)
  }, [stepIndex, effectiveSrc])

  const bboxToolAllowed = Boolean(onSaveVisualBbox && !isScrollStep && effectiveSrc)
  const handleCommitBbox = useCallback(
    async (b: { x: number; y: number; w: number; h: number }) => {
      if (!onSaveVisualBbox) return
      setBboxDrawSaving(true)
      try {
        await onSaveVisualBbox(b)
        setBboxDrawActive(false)
      } finally {
        setBboxDrawSaving(false)
      }
    },
    [onSaveVisualBbox],
  )

  const hasVisibleVisualBbox = !isWeakVisualBbox(effectiveBbox, isScrollStep)

  const canDropRecording = typeof onDroppedRecordingScreenshot === 'function'
  const canDropClear = typeof onClearStepVisual === 'function'
  const canDrop =
    typeof stepIndex === 'number' && stepIndex >= 0 && (canDropRecording || canDropClear)

  const [dropHighlight, setDropHighlight] = useState(false)

  const handleDragOver = useCallback(
    (event: DragEvent) => {
      if (!canDrop) return
      if (!recordingDragLikely(event.dataTransfer, recordingShotDragActive)) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
    },
    [canDrop, recordingShotDragActive],
  )

  const handleDragEnter = useCallback(
    (event: DragEvent) => {
      if (!canDrop) return
      if (!recordingDragLikely(event.dataTransfer, recordingShotDragActive)) return
      event.preventDefault()
      setDropHighlight(true)
    },
    [canDrop, recordingShotDragActive],
  )

  const handleDragLeave = useCallback((event: DragEvent) => {
    if (!canDrop) return
    const next = event.relatedTarget as Node | null
    if (next && event.currentTarget.contains(next)) return
    setDropHighlight(false)
  }, [canDrop])

  const handleDrop = useCallback(
    (event: DragEvent) => {
      if (!canDrop) return
      setDropHighlight(false)
      const raw = event.dataTransfer.getData(RECORDING_SCREENSHOT_DRAG_MIME).trim()
      if (!raw) return
      event.preventDefault()
      try {
        const parsed = JSON.parse(raw) as {
          mode?: unknown
          event_index?: unknown
          preview_url?: unknown
        }
        if (parsed.mode === RECORDING_DRAG_MODE_CLEAR_VISUAL) {
          if (!canDropClear || !onClearStepVisual) return
          setOptimisticSrc(null)
          setOptimisticNoImage(true)
          Promise.resolve(onClearStepVisual(stepIndex)).catch(() => {
            setOptimisticNoImage(false)
          })
          return
        }
        if (!canDropRecording || !onDroppedRecordingScreenshot) return
        const evIdx = parsed.event_index
        const previewUrl =
          typeof parsed.preview_url === 'string' && parsed.preview_url.trim() ? parsed.preview_url.trim() : null
        setOptimisticNoImage(false)
        if (typeof evIdx === 'number' && Number.isFinite(evIdx) && evIdx >= 0) {
          if (previewUrl) setOptimisticSrc(previewUrl)
          Promise.resolve(onDroppedRecordingScreenshot(stepIndex, Math.floor(evIdx))).catch(() => {
            setOptimisticSrc(null)
          })
        }
      } catch {
        setOptimisticSrc(null)
        setOptimisticNoImage(false)
      }
    },
    [canDrop, canDropClear, canDropRecording, onClearStepVisual, onDroppedRecordingScreenshot, stepIndex],
  )

  const dropAria =
    canDropRecording && canDropClear
      ? 'Drop recording frame or No image onto this screenshot area'
      : canDropClear
        ? 'Drop No image here to remove the screenshot'
        : 'Drop a recording frame here to replace the screenshot'

  if (!effectiveSrc) {
    return (
      <div
        className={cn(
          'text-muted-foreground relative rounded-xl border border-dashed border-white/10 px-3 py-6 text-center text-xs',
          canDrop &&
            dropHighlight &&
            '[box-shadow:inset_0_0_0_2px_rgba(56,189,248,0.38)] backdrop-blur-[0.5px]',
        )}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        role={canDrop ? 'region' : undefined}
        aria-label={canDrop ? dropAria : undefined}
      >
        {canDrop ? (
          <p className="text-muted-foreground/90 mb-1 text-[11px] font-medium text-zinc-400">
            Drop recording frame or No image
          </p>
        ) : null}
        No screenshot for {label}
      </div>
    )
  }

  return (
    <div
      className="relative"
      onDragOver={handleDragOver}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      role={canDrop ? 'region' : undefined}
      aria-label={canDrop ? dropAria : undefined}
    >
      <ScreenshotViewInner
        key={effectiveSrc}
        src={effectiveSrc}
        bbox={hasVisibleVisualBbox ? effectiveBbox : {}}
        dropHighlight={Boolean(canDrop && dropHighlight)}
        bboxDrawMode={bboxDrawActive}
        bboxDrawSaving={bboxDrawSaving}
        onCommitDrawnBbox={bboxToolAllowed ? handleCommitBbox : undefined}
        bboxToolUi={
          bboxToolAllowed
            ? {
                active: bboxDrawActive,
                onToggle: () => setBboxDrawActive((a) => !a),
                saving: bboxDrawSaving,
              }
            : null
        }
      />
    </div>
  )
}
