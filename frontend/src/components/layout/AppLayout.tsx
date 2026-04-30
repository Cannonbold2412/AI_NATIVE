import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FolderKanban,
  Home,
  Layers,
  Menu,
} from 'lucide-react'

const DESKTOP_SIDEBAR_KEY = 'ai-native-sidebar-collapsed'

const navItems = [
  { to: '/', label: 'Home', icon: Home, exact: true },
  { to: '/skills', label: 'Skills', icon: BookOpen, exact: false },
  { to: '/packages', label: 'Skill Packages', icon: FolderKanban, exact: false },
] as const

export function ProductMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-white shadow-sm',
        className,
      )}
      aria-hidden
    >
      <Layers className="size-4" strokeWidth={2} />
    </span>
  )
}

function SidebarNav({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean
  onNavigate?: () => void
}) {
  const location = useLocation()

  return (
    <nav className="space-y-1.5" aria-label="Primary">
      {navItems.map((item) => {
        const Icon = item.icon
        const active =
          item.exact ? location.pathname === item.to : location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.exact}
            onClick={onNavigate}
            className={cn(
              'group flex items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 text-sm transition-colors',
              'hover:border-white/8 hover:bg-white/[0.045] hover:text-white',
              active ? 'border-white/10 bg-white/[0.07] text-white' : 'text-zinc-400',
              collapsed && 'justify-center px-2.5',
            )}
            title={collapsed ? item.label : undefined}
          >
            <Icon className="size-4 shrink-0" />
            <span className={cn('truncate', collapsed && 'hidden')}>{item.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}

function SidebarRail({
  collapsed,
  setCollapsed,
}: {
  collapsed: boolean
  setCollapsed: (next: boolean) => void
}) {
  return (
    <aside
      className={cn(
        'hidden border-r border-white/8 bg-[#0d0f12] md:flex md:h-full md:min-h-0 md:flex-col md:transition-[width] md:duration-200',
        collapsed ? 'md:w-20' : 'md:w-54',
      )}
    >
      <div className="flex items-center gap-3 border-b border-white/8 px-4 py-4">
        <Link to="/" className={cn('flex min-w-0 items-center gap-3', collapsed && 'justify-center')}>
          <ProductMark />
          <div className={cn('min-w-0', collapsed && 'hidden')}>
            <p className="truncate text-sm font-semibold text-white">AI Skill Platform</p>
            <p className="truncate text-xs text-zinc-500">Recorder workspace</p>
          </div>
        </Link>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className={cn('ml-auto text-zinc-400 hover:bg-white/5 hover:text-white', collapsed && 'hidden')}
          onClick={() => setCollapsed(true)}
          aria-label="Collapse sidebar"
        >
          <ChevronLeft className="size-4" />
        </Button>
      </div>

      <div className="flex-1 space-y-6 px-3 py-4">
        {collapsed ? (
          <div className="flex justify-center">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="text-zinc-400 hover:bg-white/5 hover:text-white"
              onClick={() => setCollapsed(false)}
              aria-label="Expand sidebar"
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        ) : null}
        <SidebarNav collapsed={collapsed} />
      </div>

      <div className="border-t border-white/8 px-4 py-4">
        <div className={cn('space-y-2 rounded-lg border border-white/8 bg-white/[0.03] p-3', collapsed && 'hidden')}>
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-white">Workspace</p>
            <Badge variant="outline" className="border-white/10 bg-white/5 text-zinc-300">
              Dark
            </Badge>
          </div>
          <p className="text-xs leading-5 text-zinc-500">
            Record flows, refine steps, and review saved packages from one quiet workspace.
          </p>
        </div>
      </div>
    </aside>
  )
}

type AppShellProps = {
  title: string
  description?: ReactNode
  actions?: ReactNode
  mainClassName?: string
  children: ReactNode
}

export function AppShell({ title, description, actions, mainClassName, children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const stored = window.localStorage.getItem(DESKTOP_SIDEBAR_KEY)
    setCollapsed(stored === 'true')
  }, [])

  useEffect(() => {
    window.localStorage.setItem(DESKTOP_SIDEBAR_KEY, collapsed ? 'true' : 'false')
  }, [collapsed])

  const mobileNav = useMemo(
    () => (
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08] md:hidden"
            aria-label="Open navigation"
          >
            <Menu className="size-4" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-[18rem] border-white/10 bg-[#0d0f12] p-0 text-zinc-100">
          <SheetHeader className="border-b border-white/8 px-4 py-4 text-left">
            <div className="flex items-center gap-3">
              <ProductMark />
              <div>
                <SheetTitle className="text-white">AI Skill Platform</SheetTitle>
                <SheetDescription className="text-zinc-500">Recorder workspace</SheetDescription>
              </div>
            </div>
          </SheetHeader>
          <div className="px-3 py-4">
            <SidebarNav collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    ),
    [mobileOpen],
  )

  return (
    <div className="h-dvh overflow-hidden bg-[#0a0c0f] text-zinc-100">
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.05),_transparent_40%),linear-gradient(180deg,_#0f1115_0%,_#090b0d_100%)]" />
        <div
          className="absolute inset-0 opacity-[0.18]"
          style={{
            backgroundImage: 'radial-gradient(rgba(255,255,255,0.08) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />
      </div>

      <div className="flex h-full min-h-0">
        <SidebarRail collapsed={collapsed} setCollapsed={setCollapsed} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 border-b border-white/8 bg-[#0b0d10]/88 backdrop-blur">
            <div className="flex min-h-16 items-center gap-3 px-4 py-3 sm:px-6">
              {mobileNav}
              <div className="min-w-0 flex-1">
                <h1
                  className={cn(
                    'truncate text-base font-semibold text-white sm:text-lg',
                    description != null && description !== false && 'leading-snug',
                  )}
                >
                  {title}
                </h1>
                {description != null && description !== false ? (
                  <div
                    className={cn(
                      'mt-0 min-w-0',
                      typeof description === 'string' ? 'truncate text-sm text-zinc-500' : 'text-zinc-500',
                    )}
                  >
                    {description}
                  </div>
                ) : null}
              </div>
              {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
            </div>
          </header>

          <main className={cn('min-h-0 flex-1 overflow-hidden', mainClassName)}>{children}</main>
        </div>
      </div>
    </div>
  )
}
