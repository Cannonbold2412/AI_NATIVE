'use client'

import { type ReactNode, useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { OrganizationSwitcher, UserButton, useOrganization } from '@clerk/nextjs'
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
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Home,
  Menu,
  Puzzle,
  Settings,
  Users,
} from 'lucide-react'
import { clerkAppearance } from '@/lib/clerkAppearance'

const SIDEBAR_KEY = 'conxa-sidebar-collapsed'

const navGroups = [
  {
    label: 'Operate',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: Home },
      { to: '/plugins', label: 'Plugins', icon: Puzzle },
    ],
  },
  {
    label: 'Manage',
    items: [
      { to: '/team', label: 'Team', icon: Users },
      { to: '/billing', label: 'Billing', icon: CreditCard },
      { to: '/settings', label: 'Settings', icon: Settings },
    ],
  },
] as const

function ProductMark() {
  return (
    <span
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-white shadow-sm"
      aria-hidden
    >
      <img src="/conxa-icon.png" alt="" width={24} height={24} className="h-6 w-6 object-contain" />
    </span>
  )
}

function SidebarNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname()
  return (
    <nav className="space-y-1.5" aria-label="Primary">
      {navGroups.map((group) => (
        <div key={group.label} className="space-y-1.5">
          <p className={cn('px-3 pt-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-600', collapsed && 'sr-only')}>
            {group.label}
          </p>
          {group.items.map((item) => {
            const Icon = item.icon
            const active = pathname === item.to || pathname.startsWith(`${item.to}/`)
            return (
              <Link
                key={item.to}
                href={item.to}
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
              </Link>
            )
          })}
        </div>
      ))}
    </nav>
  )
}

function OrgName({ collapsed }: { collapsed: boolean }) {
  const { organization } = useOrganization()
  if (collapsed) return null
  return (
    <div className="min-w-0">
      <p className="truncate text-sm font-semibold text-white">{organization?.name ?? 'Conxa'}</p>
      <p className="truncate text-xs text-zinc-500">Workspace</p>
    </div>
  )
}

function DesktopSidebar({ collapsed, setCollapsed }: { collapsed: boolean; setCollapsed: (v: boolean) => void }) {
  return (
    <aside
      className={cn(
        'hidden border-r border-white/8 bg-[#0d0f12] md:flex md:h-full md:min-h-0 md:flex-col md:transition-[width] md:duration-200',
        collapsed ? 'md:w-20' : 'md:w-54',
      )}
    >
      <div className="flex items-center gap-3 border-b border-white/8 px-4 py-4">
        <Link href="/dashboard" className={cn('flex min-w-0 items-center gap-3', collapsed && 'justify-center')}>
          <ProductMark />
          <OrgName collapsed={collapsed} />
        </Link>
        {!collapsed && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="ml-auto text-zinc-400 hover:bg-white/5 hover:text-white"
            onClick={() => setCollapsed(true)}
            aria-label="Collapse sidebar"
          >
            <ChevronLeft className="size-4" />
          </Button>
        )}
      </div>

      <div className="flex-1 space-y-6 px-3 py-4">
        {collapsed && (
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
        )}
        <SidebarNav collapsed={collapsed} />
      </div>
    </aside>
  )
}

export function AppChrome({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(SIDEBAR_KEY) === 'true')
  }, [])

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_KEY, collapsed ? 'true' : 'false')
  }, [collapsed])

  return (
    <div className="h-dvh overflow-hidden bg-[#0a0c0f] text-zinc-100">
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.05),_transparent_40%),linear-gradient(180deg,_#0f1115_0%,_#090b0d_100%)]" />
        <div
          className="absolute inset-0 opacity-[0.18]"
          style={{ backgroundImage: 'radial-gradient(rgba(255,255,255,0.08) 1px, transparent 1px)', backgroundSize: '24px 24px' }}
        />
      </div>

      <div className="flex h-full min-h-0">
        <DesktopSidebar collapsed={collapsed} setCollapsed={setCollapsed} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Global topbar */}
          <header className="sticky top-0 z-30 border-b border-white/8 bg-[#0b0d10]/88 backdrop-blur">
            <div className="flex min-h-14 items-center gap-3 px-4 sm:px-6">
              {/* Mobile nav sheet */}
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
                        <SheetTitle className="text-white">Conxa</SheetTitle>
                        <SheetDescription className="text-zinc-500">Workspace</SheetDescription>
                      </div>
                    </div>
                  </SheetHeader>
                  <div className="px-3 py-4">
                    <SidebarNav collapsed={false} onNavigate={() => setMobileOpen(false)} />
                  </div>
                </SheetContent>
              </Sheet>

              <div className="flex-1" />

              {/* Org switcher */}
              <OrganizationSwitcher
                hidePersonal
                afterSelectOrganizationUrl="/dashboard"
                afterCreateOrganizationUrl="/dashboard"
                appearance={{
                  ...clerkAppearance,
                  elements: {
                    ...clerkAppearance.elements,
                    rootBox: 'text-zinc-300',
                    organizationSwitcherTrigger:
                      'flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-white/[0.06] transition-colors',
                    organizationSwitcherPopoverCard: 'bg-[#0d0f12] border border-white/10 shadow-xl',
                    organizationSwitcherPopoverActionButton: 'text-zinc-300 hover:bg-white/5',
                    organizationPreviewTextContainer: 'text-zinc-200',
                  },
                }}
              />

              <UserButton
                appearance={{
                  ...clerkAppearance,
                  elements: {
                    ...clerkAppearance.elements,
                    avatarBox: 'size-8',
                    userButtonAvatarBox: 'size-8',
                  },
                }}
              />
            </div>
          </header>

          <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
        </div>
      </div>
    </div>
  )
}
