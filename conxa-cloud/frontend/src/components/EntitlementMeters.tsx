'use client'

import { useQuery } from '@tanstack/react-query'
import { fetchEntitlements, type EntitlementMeter, type EntitlementMeterKey } from '@/api/productApi'

const LABELS: Record<EntitlementMeterKey, string> = {
  seats: 'Seats',
  installer_slots: 'Installer slots',
  compile_credits: 'Compile credits',
  human_edit_tokens: 'Human Edit pool',
}

const DEFAULT_METERS: EntitlementMeterKey[] = ['seats', 'installer_slots', 'compile_credits', 'human_edit_tokens']

function formatCount(value: number | null | undefined, key: EntitlementMeterKey) {
  if (value == null) return 'Unlimited'
  if (key === 'human_edit_tokens' && value >= 1_000_000) return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`
  return new Intl.NumberFormat().format(value)
}

function meterText(meter: EntitlementMeter | undefined, key: EntitlementMeterKey) {
  if (!meter) return 'Unavailable'
  if (meter.unlimited) return `${formatCount(meter.used, key)} used`
  return `${formatCount(meter.used, key)} of ${formatCount(meter.limit, key)}`
}

export function EntitlementMeters({ meters = DEFAULT_METERS }: { meters?: EntitlementMeterKey[] }) {
  const q = useQuery({ queryKey: ['entitlements'], queryFn: fetchEntitlements, staleTime: 30_000, retry: 1 })

  if (q.isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {meters.map((key) => <div key={key} className="h-20 animate-pulse rounded-lg border border-white/8 bg-white/[0.03]" />)}
      </div>
    )
  }

  if (q.isError) {
    return (
      <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
        Entitlement meters are unavailable.
      </div>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {meters.map((key) => {
        const meter = q.data?.meters?.[key]
        const remaining = meter?.unlimited ? 'Unlimited' : formatCount(meter?.remaining, key)
        return (
          <div key={key} className="rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2.5">
            <p className="text-[11px] font-medium uppercase text-zinc-500">{LABELS[key]}</p>
            <p className="mt-1 text-sm font-medium text-white">{meterText(meter, key)}</p>
            <p className="mt-0.5 text-xs text-zinc-500">{remaining} remaining</p>
          </div>
        )
      })}
    </div>
  )
}
