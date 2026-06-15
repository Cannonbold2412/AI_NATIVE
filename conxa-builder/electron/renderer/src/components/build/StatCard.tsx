import { type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type StatCardProps = {
  label: string
  value: ReactNode
  subvalue?: ReactNode
  accent?: 'emerald' | 'amber' | 'sky' | 'zinc'
  icon?: ReactNode
}

const accentMap = {
  emerald: 'text-emerald-400',
  amber: 'text-amber-400',
  sky: 'text-sky-400',
  zinc: 'text-zinc-400',
}

export function StatCard({ label, value, subvalue, accent = 'zinc', icon }: StatCardProps) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-white/8 bg-white/[0.03] px-4 py-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-zinc-500">
        {icon && <span className="size-3.5 shrink-0">{icon}</span>}
        {label}
      </div>
      <p className={cn('text-xl font-semibold leading-none', accentMap[accent])}>{value}</p>
      {subvalue != null && (
        <p className="text-[11px] text-zinc-600 leading-tight">{subvalue}</p>
      )}
    </div>
  )
}
