import { cmd } from '@/lib/ipc'

export type EntitlementMeterKey = 'seats' | 'installer_slots' | 'compile_credits' | 'human_edit_tokens'

export interface EntitlementMeter {
  used: number
  limit: number | null
  remaining: number | null
  unlimited: boolean
}

export interface EntitlementResponse {
  workspace_id?: string
  plan?: string
  period?: string
  reset_at?: string
  meters?: Partial<Record<EntitlementMeterKey, EntitlementMeter>>
  entitlements_unavailable?: boolean
  error?: { code?: string; message?: string }
}

export async function fetchEntitlements(): Promise<EntitlementResponse> {
  const response = await cmd<EntitlementResponse>('get_usage', {})
  if (response?.meters) return response
  const nested = (response as { entitlements?: EntitlementResponse } | null)?.entitlements
  if (nested?.meters) return nested
  return response ?? {}
}
