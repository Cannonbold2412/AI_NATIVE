'use client'

import { useEffect, useRef, useState } from 'react'
import { Monitor, Download, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getStudioManifest } from '@/api/pluginApi'

interface Props {
  pluginId?: string
  size?: 'sm' | 'default'
}

export function OpenInStudioButton({ pluginId, size = 'sm' }: Props) {
  const [open, setOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  const deepLink = pluginId
    ? `conxa-studio://open?plugin=${encodeURIComponent(pluginId)}`
    : 'conxa-studio://open'

  function launch(e: React.MouseEvent) {
    e.stopPropagation()
    window.location.href = deepLink
    setOpen(true)
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

  // Close on outside click
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

  return (
    <div ref={wrapperRef} className="relative">
      {size === 'default' ? (
        <Button
          variant="outline"
          size="sm"
          className="border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10 hover:text-white gap-1.5"
          onClick={launch}
        >
          <Monitor className="size-3.5" />
          Open in Studio
        </Button>
      ) : (
        <Button
          size="icon-sm"
          variant="ghost"
          className="text-zinc-400 hover:text-white"
          title="Open in Build Studio"
          onClick={launch}
        >
          <Monitor className="size-4" />
        </Button>
      )}

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-lg border border-white/10 bg-[#0d0f12] p-3 shadow-xl">
          <div className="flex items-start justify-between gap-2 mb-2">
            <p className="text-sm font-medium text-white">Launching Build Studio…</p>
            <button
              onClick={(e) => { e.stopPropagation(); setOpen(false) }}
              className="shrink-0 text-zinc-500 hover:text-zinc-300"
            >
              <X className="size-3.5" />
            </button>
          </div>
          <p className="mb-2.5 text-xs text-zinc-400">
            If nothing happened, Build Studio may not be installed yet.
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
