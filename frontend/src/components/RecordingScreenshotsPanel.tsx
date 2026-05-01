import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { RecordingScreenshotItemDTO } from '@/api/workflowApi'
import {
  RECORDING_DRAG_MODE_CLEAR_VISUAL,
  RECORDING_SCREENSHOT_DRAG_MIME,
} from '@/api/workflowApi'
import { ImageIcon, ImageOff } from 'lucide-react'

type Props = {
  loading: boolean
  error: Error | null
  items: RecordingScreenshotItemDTO[]
  /** Recording thumbnails: drag disabled when false (no session / no frames). */
  recordingDragEnabled?: boolean
  /** “No image” chip — clears step screenshots; on by default. */
  clearVisualDragEnabled?: boolean
  emptyDetail?: string | null
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
          if (!enabled) {
            e.preventDefault()
            return
          }
          onDragShotStart?.()
          e.dataTransfer.effectAllowed = 'copy'
          e.dataTransfer.setData(
            RECORDING_SCREENSHOT_DRAG_MIME,
            JSON.stringify({ mode: RECORDING_DRAG_MODE_CLEAR_VISUAL }),
          )
        }}
        onDragEnd={() => {
          if (!enabled) return
          onDragShotEnd?.()
        }}
        className={`border-border flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-t-md border-b border-white/[0.07] px-3 py-8 outline-none ring-offset-2 ${
          enabled ? 'cursor-grab bg-black/20 active:cursor-grabbing group-hover:bg-black/35 group-hover:ring-2 group-hover:ring-orange-400/35' : 'cursor-not-allowed opacity-55'
        }`}
        title={enabled ? 'Drag onto a step or the main preview — removes screenshot and vision anchors' : ''}
      >
        <ImageOff className="text-muted-foreground size-10 opacity-75" aria-hidden strokeWidth={1.5} />
        <span className="text-muted-foreground text-[11px] font-medium uppercase tracking-wide">No image</span>
      </div>
      <figcaption className="text-muted-foreground flex items-center justify-between gap-1 px-2 py-1 text-[10px]">
        <span>0 · clear screenshot</span>
        <Badge variant="outline" className="h-5 shrink-0 border-white/15 px-1 text-[10px] text-zinc-500">
          detach
        </Badge>
      </figcaption>
    </figure>
  )
}

/** Recording frames list + draggable “No image” to detach screenshots from a step. */
export function RecordingScreenshotsPanel({
  loading,
  error,
  items,
  recordingDragEnabled = true,
  clearVisualDragEnabled = true,
  emptyDetail,
  onDragShotStart,
  onDragShotEnd,
}: Props) {
  const blurb =
    items.length || loading
      ? 'Drag No image first to detach a screenshot, or drag a frame to replace it and rerun vision anchors on the preview or a workflow step.'
      : `${emptyDetail ?? 'No recording frames for this skill. You can still drag No image onto a step to remove its screenshot.'}`

  if (loading) {
    return (
      <div className="flex h-full min-h-0 flex-col space-y-2">
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overflow-x-hidden pb-2">
          {clearVisualDragEnabled ? (
            <NoImageDragChip enabled={true} onDragShotStart={onDragShotStart} onDragShotEnd={onDragShotEnd} />
          ) : null}
          {[0, 1, 2, 3].map((k) => (
            <Skeleton key={k} className="border-border aspect-video w-full shrink-0 rounded-lg border" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full min-h-0 flex-col space-y-2">
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overflow-x-hidden pb-2">
          {clearVisualDragEnabled ? (
            <NoImageDragChip enabled={true} onDragShotStart={onDragShotStart} onDragShotEnd={onDragShotEnd} />
          ) : null}
          <p className="text-muted-foreground text-xs break-words">Could not load recording frames: {error.message}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col space-y-2">
      <p className="text-muted-foreground text-xs leading-relaxed">{blurb}</p>
      {!items.length ? (
        <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto overflow-x-hidden pb-1 pr-0.5">
          {clearVisualDragEnabled ? (
            <NoImageDragChip enabled={true} onDragShotStart={onDragShotStart} onDragShotEnd={onDragShotEnd} />
          ) : null}
          <p className="text-muted-foreground px-0.5 text-xs">{emptyDetail ?? ''}</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto overflow-x-hidden pb-1 pr-0.5">
          {clearVisualDragEnabled ? (
            <NoImageDragChip enabled={true} onDragShotStart={onDragShotStart} onDragShotEnd={onDragShotEnd} />
          ) : null}
          {items.map((shot) => (
            <figure
              key={`${shot.event_index}-${shot.sequence}`}
              className="border-border bg-muted/40 group w-full shrink-0 overflow-hidden rounded-lg border"
            >
              <img
                src={shot.preview_url}
                alt=""
                role="presentation"
                width={352}
                height={198}
                draggable={recordingDragEnabled}
                loading="lazy"
                className={`aspect-video block w-full rounded-t-md object-cover object-top outline-none ring-offset-2 ${
                  recordingDragEnabled ? 'cursor-grab active:cursor-grabbing group-hover:ring-2 group-hover:ring-sky-500/40' : 'opacity-80'
                }`}
                title={recordingDragEnabled ? 'Drag onto the step preview or a workflow step' : ''}
                onDragStart={(e) => {
                  if (!recordingDragEnabled) {
                    e.preventDefault()
                    return
                  }
                  onDragShotStart?.()
                  e.dataTransfer.effectAllowed = 'copy'
                  e.dataTransfer.setData(
                    RECORDING_SCREENSHOT_DRAG_MIME,
                    JSON.stringify({
                      event_index: shot.event_index,
                      sequence: shot.sequence,
                      preview_url: shot.preview_url,
                    }),
                  )
                }}
                onDragEnd={() => {
                  if (!recordingDragEnabled) return
                  onDragShotEnd?.()
                }}
              />
              <figcaption className="flex items-center justify-between gap-1 border-t border-white/[0.07] px-1.5 py-1">
                <span className="text-muted-foreground flex items-center gap-0.5 text-[10px] font-medium">
                  <ImageIcon className="size-3 shrink-0" aria-hidden />#{shot.sequence}
                </span>
                <Badge variant="outline" className="h-5 shrink-0 border-white/15 px-1 text-[10px] text-zinc-400">
                  ev {shot.event_index}
                </Badge>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  )
}
