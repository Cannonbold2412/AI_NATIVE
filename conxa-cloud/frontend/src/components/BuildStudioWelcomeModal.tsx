'use client'

import { useEffect, useState } from 'react'
import { Monitor, Download, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { getStudioManifest } from '@/api/pluginApi'

const STORAGE_KEY = 'conxa.studio.welcome.v1'
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

function shouldShow(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return true
    const ts = parseInt(raw, 10)
    return isNaN(ts) || Date.now() - ts > COOLDOWN_MS
  } catch {
    return false
  }
}

function dismiss() {
  try {
    localStorage.setItem(STORAGE_KEY, String(Date.now()))
  } catch {
    // ignore — storage unavailable
  }
}

export function BuildStudioWelcomeModal() {
  const [open, setOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    if (shouldShow()) setOpen(true)
  }, [])

  function handleOpen() {
    window.location.href = 'conxa-studio://open'
    dismiss()
    setOpen(false)
  }

  function handleDismiss() {
    dismiss()
    setOpen(false)
  }

  async function handleDownload() {
    setDownloading(true)
    try {
      const manifest = await getStudioManifest()
      if (manifest.win_url) window.open(manifest.win_url, '_blank', 'noopener')
    } finally {
      setDownloading(false)
      dismiss()
      setOpen(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) handleDismiss() }}>
      <DialogContent
        showCloseButton={false}
        className="w-full max-w-sm border-white/10 bg-[#0d0f12] p-0 text-zinc-100 shadow-2xl"
      >
        {/* Header strip */}
        <div className="flex items-start justify-between gap-3 border-b border-white/8 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.05]">
              <Monitor className="size-4 text-blue-400" />
            </span>
            <div>
              <DialogHeader className="gap-0.5">
                <DialogTitle className="text-sm font-semibold text-zinc-100">
                  Open in Build Studio?
                </DialogTitle>
                <DialogDescription className="text-xs text-zinc-500">
                  conxa.ai wants to open this application
                </DialogDescription>
              </DialogHeader>
            </div>
          </div>
          <button
            onClick={handleDismiss}
            className="shrink-0 text-zinc-600 transition-colors hover:text-zinc-300"
            aria-label="Dismiss"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          <p className="text-sm leading-5 text-zinc-400">
            Your workspace is ready. Build Studio is your local environment
            for recording, compiling, and testing automation workflows.
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 border-t border-white/8 bg-white/[0.02] px-5 py-4 rounded-b-xl">
          <Button
            onClick={handleOpen}
            className="w-full bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700"
            size="sm"
          >
            <Monitor className="size-3.5" />
            Open Build Studio
          </Button>
          <Button
            onClick={handleDismiss}
            variant="ghost"
            size="sm"
            className="w-full border border-white/8 text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200"
          >
            Continue in browser
          </Button>
          <div className="mt-1 text-center">
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="text-[11px] text-zinc-600 underline-offset-2 transition-colors hover:text-zinc-400 hover:underline disabled:opacity-50"
            >
              {downloading ? 'Getting download link…' : "Don't have it? Download Conxa Build Studio"}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
