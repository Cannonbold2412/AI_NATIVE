import { type ReactNode, useEffect, useState } from 'react'
import { Copy, Minus, Square, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const logoUrl = new URL('../../assets/conxa-icon.png', import.meta.url).href

function WindowButton({
  label,
  className,
  onClick,
  children,
}: {
  label: string
  className?: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      title={label}
      className={cn('app-region-no-drag h-8 w-10 rounded-none text-zinc-400 hover:bg-white/8 hover:text-white', className)}
      onClick={onClick}
    >
      {children}
    </Button>
  )
}

export function WindowTitleBar() {
  const [isMaximized, setIsMaximized] = useState(false)

  useEffect(() => {
    let mounted = true

    void window.conxa.windowControls.isMaximized().then((value) => {
      if (mounted) setIsMaximized(value)
    })

    const unsubscribe = window.conxa.windowControls.onMaximizeChange(setIsMaximized)
    return () => {
      mounted = false
      unsubscribe()
    }
  }, [])

  const handleToggleMaximize = () => {
    void window.conxa.windowControls.toggleMaximize().then(setIsMaximized)
  }

  return (
    <div className="app-region-drag flex h-10 shrink-0 select-none items-center border-b border-white/8 bg-[#111418] text-zinc-200">
      <div className="flex min-w-0 items-center gap-2 px-3">
        <img src={logoUrl} alt="" className="h-4 w-4 shrink-0" draggable={false} />
        <span className="truncate text-xs font-medium">Conxa Build Studio</span>
      </div>

      <div className="min-w-0 flex-1" />

      <div className="app-region-no-drag flex h-full items-center">
        <WindowButton label="Minimize" onClick={() => void window.conxa.windowControls.minimize()}>
          <Minus className="size-4" />
        </WindowButton>
        <WindowButton label={isMaximized ? 'Restore' : 'Maximize'} onClick={handleToggleMaximize}>
          {isMaximized ? <Copy className="size-3.5" /> : <Square className="size-3.5" />}
        </WindowButton>
        <WindowButton
          label="Close"
          className="hover:bg-red-500 hover:text-white"
          onClick={() => void window.conxa.windowControls.close()}
        >
          <X className="size-4" />
        </WindowButton>
      </div>
    </div>
  )
}
