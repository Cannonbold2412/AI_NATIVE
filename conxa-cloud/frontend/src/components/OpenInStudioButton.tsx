'use client'

import { useEffect, useRef, useState } from 'react'
import { Monitor, Download, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getStudioManifest } from '@/api/pluginApi'

interface Props {
  pluginId?: string
  /** Button size. Defaults to 'sm' (icon-only ghost). Pass 'default' for labelled outline button. */
  size?: 'sm' | 'default'
  /** Override the button label. Only shown when size='default'. Defaults to 'Open in Studio'. */
  label?: string
  /** Render as a filled primary button (e.g. for "Create a Plugin" CTAs). */
  primary?: boolean
}

export function OpenInStudioButton({ pluginId, size = 'sm', label = 'Open in Studio', primary = false }: Props) {
  const [open, setOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const deepLink = pluginId
    ? `conxa-studio://open?plugin=${encodeURIComponent(pluginId)}`
    : 'conxa-studio://open'

  function launch(e: React.MouseEvent) {
    e.stopPropagation()

    // Detect whether the deep link successfully opened the app by watching
    // whether the tab loses focus (blur / visibilitychange). If it doesn't
    // within 1500 ms, assume Build Studio is not installed and show the
    // download popover.
    let didHide = false

    function onHide() {
      didHide = true
    }

    document.addEventListener('visibilitychange', onHide)
    window.addEventListener('blur', onHide)

    window.location.href = deepLink

    timerRef.current = setTimeout(() => {
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('blur', onHide)
      timerRef.current = null
      if (!didHide) {
        // Tab is still focused — app probably isn't installed
        setOpen(true)
      }
    }, 1500)
  }

  async function handleDownload(e: React.MouseEvent) {
    e.stopPropagation()
    setDownloading(true)
    try {
      const manifest = await getStudioManifest()
      if (manifest.win_url) window.open(manifest.win_url, '_blank', 'noopener')
    } finally {
      setDownloading(false)
    }
  }

  // Close popover on outside click
  useEffect(() => {
    if (!open) return
    function onPointerDown(e: PointerEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return (
    <div ref={wrapperRef} className="relative">
      {primary ? (
        <Button
          variant="default"
          size="sm"
          className="gap-1.5 cursor-pointer"
          onClick={launch}
        >
          <Monitor className="size-3.5" />
          {label}
        </Button>
      ) : size === 'default' ? (
        <Button
          variant="outline"
          size="sm"
          className="border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10 hover:text-white gap-1.5 cursor-pointer"
          onClick={launch}
        >
          <Monitor className="size-3.5" />
          {label}
        </Button>
      ) : (
        <Button
          size="icon-sm"
          variant="ghost"
          className="text-zinc-400 hover:text-white cursor-pointer"
          title="Open in Build Studio"
          onClick={launch}
        >
          <Monitor className="size-4" />
        </Button>
      )}

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-lg border border-white/10 bg-[#0d0f12] p-3 shadow-xl">
          <div className="flex items-start justify-between gap-2 mb-2">
            <p className="text-sm font-medium text-white">Build Studio not found</p>
            <button
              onClick={(e) => { e.stopPropagation(); setOpen(false) }}
              className="shrink-0 text-zinc-500 hover:text-zinc-300"
            >
              <X className="size-3.5" />
            </button>
          </div>
          <p className="mb-2.5 text-xs text-zinc-400">
            Conxa Build Studio doesn&apos;t appear to be installed on this computer.
          </p>
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="flex w-full items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white disabled:opacity-50"
          >
            <Download className="size-3.5 shrink-0" />
            {downloading ? 'Getting download link…' : 'Download Conxa Build Studio'}
          </button>
        </div>
      )}
    </div>
  )
}
