import { useMemo, useState } from 'react'
import type { StepScreenshotDTO } from '../types/workflow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

type InnerProps = {
  src: string
  bbox: Record<string, unknown>
}

function ScreenshotViewInner({ src, bbox }: InnerProps) {
  const { x = 0, y = 0, w = 0, h = 0 } = bbox as Record<string, number>
  const [zoom, setZoom] = useState(1)
  const [resolvedSrc, setResolvedSrc] = useState(src || '')
  const [fallbackTried, setFallbackTried] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [natural, setNatural] = useState({ w: 0, h: 0 })

  const overlayPct = useMemo(() => {
    if (!natural.w || !natural.h || !w || !h) return null
    return {
      left: `${(x / natural.w) * 100}%`,
      top: `${(y / natural.h) * 100}%`,
      width: `${(w / natural.w) * 100}%`,
      height: `${(h / natural.h) * 100}%`,
    }
  }, [x, y, w, h, natural.w, natural.h])

  return (
    <Card className="border-border bg-card/20 overflow-hidden">
      <CardHeader className="flex flex-col gap-2 space-y-0 p-3 sm:flex-row sm:items-center sm:justify-between sm:pr-2">
        <CardTitle className="text-sm font-medium">Screenshot</CardTitle>
        <div className="flex flex-wrap items-center gap-1">
          <Button type="button" size="icon-sm" variant="secondary" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} aria-label="Zoom out">
            −
          </Button>
          <span className="text-muted-foreground w-9 text-center text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
          <Button type="button" size="icon-sm" variant="secondary" onClick={() => setZoom((z) => Math.min(3, z + 0.25))} aria-label="Zoom in">
            +
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setZoom(1)} aria-label="Reset zoom">
            Reset
          </Button>
        </div>
      </CardHeader>
      <Separator />
      <CardContent className="p-0">
        <div className="max-h-72 overflow-auto p-2">
          <div
            className="bg-muted/20 inline-block min-w-0"
            style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
          >
            <div className="shot-wrap relative inline-block min-w-0 max-w-full">
              <img
                src={resolvedSrc}
                alt="Captured page region for this step"
                className="max-w-full h-auto"
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
                  className="ring-primary/50 pointer-events-none absolute border-2"
                  style={overlayPct}
                  title="Target region"
                />
              ) : null}
            </div>
          </div>
        </div>
        {loadError ? <p className="text-destructive p-2 text-sm">{loadError}</p> : null}
      </CardContent>
    </Card>
  )
}

type Props = {
  screenshot: StepScreenshotDTO
  label: string
}

export function ScreenshotViewer({ screenshot, label }: Props) {
  const src = screenshot.full_url || screenshot.element_url || screenshot.scroll_url
  const bbox = screenshot.bbox || {}

  if (!src) {
    return (
      <div className="text-muted-foreground p-2 text-sm">
        No screenshot for {label}
      </div>
    )
  }

  return <ScreenshotViewInner key={src} src={src} bbox={bbox} />
}
