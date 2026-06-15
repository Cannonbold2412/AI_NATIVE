import { Badge } from '@/components/ui/badge'
import { ImageOff } from 'lucide-react'
import type { FrameDTO } from '@/types/workflow'
import {
  RECORDING_DRAG_MODE_CLEAR_VISUAL,
  RECORDING_SCREENSHOT_DRAG_MIME,
} from '@/api/workflowApi'

const FRAME_LABELS: Record<string, string> = {
  before_far: '−0.5 s',
  before_near: '−0.25 s',
  at: '0 s',
  after_near: '+0.25 s',
  after_far: '+0.5 s',
}

type Props = {
  frames: FrameDTO[]
  /** Label currently applied as the representative (from signals.visual.default_frame_label). */
  activeFrameLabel: string | null
  clearVisualDragEnabled?: boolean
  onApplyFrame?: (label: string) => void | Promise<void>
  onDragShotStart?: () => void
  onDragShotEnd?: () => void
}

function NoImageDragChip({
  enabled,
  onDragShotStart,
  onDragShotEnd,
}: {
  enabled: boolean
  onDragShotStart?: () => void
  onDragShotEnd?: () => void
}) {
  return (
    <figure className="border-border bg-muted/25 group mb-2 w-full shrink-0 overflow-hidden rounded-lg border border-dashed border-white/20">
      <div
        draggable={enabled}
        onDragStart={(e) => {
          if (!enabled) { e.preventDefault(); return }
          onDragShotStart?.()
          e.dataTransfer.effectAllowed = 'copy'
          e.dataTransfer.setData(
            RECORDING_SCREENSHOT_DRAG_MIME,
            JSON.stringify({ mode: RECORDING_DRAG_MODE_CLEAR_VISUAL }),
          )
        }}
        onDragEnd={() => { if (!enabled) return; onDragShotEnd?.() }}
        className={`border-border flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-t-md border-b border-white/[0.07] px-3 py-8 outline-none ring-offset-2 ${
          enabled
            ? 'cursor-grab bg-black/20 active:cursor-grabbing group-hover:bg-black/35 group-hover:ring-2 group-hover:ring-orange-400/35'
            : 'cursor-not-allowed opacity-55'
        }`}
        title={enabled ? 'Drag onto a step or the main preview — removes screenshot and vision anchors' : ''}
      >
        <ImageOff className="text-muted-foreground size-10 opacity-75" aria-hidden strokeWidth={1.5} />
        <span className="text-muted-foreground text-[11px] font-medium uppercase tracking-wide">No image</span>
      </div>
      <figcaption className="text-muted-foreground flex items-center justify-between gap-1 px-2 py-1 text-[10px]">
        <span>clear screenshot</span>
        <Badge variant="outline" className="h-5 shrink-0 border-white/15 px-1 text-[10px] text-zinc-500">
          detach
        </Badge>
      </figcaption>
    </figure>
  )
}

/** 5-frame video picker for the currently-selected step. Drag or click to apply a frame. */
export function RecordingScreenshotsPanel({
  frames,
  activeFrameLabel,
  clearVisualDragEnabled = true,
  onApplyFrame,
  onDragShotStart,
  onDragShotEnd,
}: Props) {
  const hasFrames = frames.length > 0

  return (
    <div className="flex h-full min-h-0 flex-col space-y-2">
      <p className="text-muted-foreground text-xs leading-relaxed">
        {hasFrames
          ? 'Click or drag a frame to set it as the representative screenshot. The default (−0.25 s) is selected automatically.'
          : 'No video frames for this step. Compile the skill from a recording session to generate frames.'}
      </p>
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto overflow-x-hidden pb-1 pr-0.5">
        {clearVisualDragEnabled ? (
          <NoImageDragChip enabled={clearVisualDragEnabled} onDragShotStart={onDragShotStart} onDragShotEnd={onDragShotEnd} />
        ) : null}
        {frames.map((frame) => {
          const isActive = frame.label === activeFrameLabel
          const isDefault = frame.label === 'before_near'
          const timeLabel = FRAME_LABELS[frame.label] ?? frame.label
          return (
            <figure
              key={frame.label}
              className={`border-border bg-muted/40 group w-full shrink-0 overflow-hidden rounded-lg border transition-all ${
                isActive ? 'ring-2 ring-sky-400/60 border-sky-400/40' : ''
              }`}
            >
              {frame.url ? (
                <img
                  src={frame.url}
                  alt={`Frame at ${timeLabel}`}
                  width={352}
                  height={198}
                  draggable={!!onApplyFrame}
                  loading="lazy"
                  className={`aspect-video block w-full rounded-t-md object-cover object-top outline-none ring-offset-2 ${
                    onApplyFrame
                      ? 'cursor-pointer active:cursor-grabbing group-hover:ring-2 group-hover:ring-sky-500/40'
                      : 'opacity-80'
                  }`}
                  title={`Frame at ${timeLabel}${isDefault ? ' (default)' : ''}${isActive ? ' — active' : ''}`}
                  onClick={() => onApplyFrame?.(frame.label)}
                  onDragStart={(e) => {
                    if (!onApplyFrame) { e.preventDefault(); return }
                    onDragShotStart?.()
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData(
                      RECORDING_SCREENSHOT_DRAG_MIME,
                      JSON.stringify({ frame_label: frame.label, preview_url: frame.url }),
                    )
                  }}
                  onDragEnd={() => { if (!onApplyFrame) return; onDragShotEnd?.() }}
                />
              ) : (
                <div className="aspect-video flex items-center justify-center rounded-t-md bg-black/30">
                  <span className="text-muted-foreground text-[10px]">no image</span>
                </div>
              )}
              <figcaption className="flex items-center justify-between gap-1 border-t border-white/[0.07] px-1.5 py-1">
                <span className="text-muted-foreground flex items-center gap-1.5 text-[10px] font-medium">
                  {timeLabel}
                  {isDefault && (
                    <Badge variant="outline" className="h-4 border-amber-500/30 px-1 text-[9px] text-amber-400">
                      default
                    </Badge>
                  )}
                </span>
                {isActive && (
                  <Badge variant="outline" className="h-4 border-sky-500/30 px-1 text-[9px] text-sky-300">
                    active
                  </Badge>
                )}
              </figcaption>
            </figure>
          )
        })}
      </div>
    </div>
  )
}
