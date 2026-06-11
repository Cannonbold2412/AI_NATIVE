'use client'

import { useEffect, useMemo, useState, type ComponentType } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  CreditCard,
  Loader2,
  Mail,
  PackageCheck,
  PhoneCall,
  RefreshCw,
  Users,
  Wand2,
} from 'lucide-react'
import {
  createRazorpaySubscription,
  listPlans,
  verifyRazorpaySubscription,
  type Plan,
} from '@/api/razorpayApi'
import {
  fetchEntitlements,
  fetchSubscription,
  type EntitlementMeter,
  type EntitlementMeterKey,
} from '@/api/productApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => { open: () => void }
  }
}

type RazorpayOptions = {
  key: string
  subscription_id: string
  name: string
  description: string
  handler: (response: {
    razorpay_payment_id: string
    razorpay_subscription_id: string
    razorpay_signature: string
  }) => void | Promise<void>
  modal?: {
    ondismiss?: () => void
  }
  theme?: {
    color: string
  }
}

type CheckoutStatus = 'missing_key' | 'loading' | 'ready' | 'failed'

type UsageMeterConfig = {
  key: EntitlementMeterKey
  label: string
  description: string
  icon: ComponentType<{ className?: string }>
}

const RAZORPAY_CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js'
const RAZORPAY_KEY_ID = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID ?? ''
const SALES_EMAIL = 'noreplay@conxa.in'
const SALES_PHONE_DISPLAY = process.env.NEXT_PUBLIC_SALES_PHONE_DISPLAY ?? '+91 9970257247'
const SALES_PHONE_TEL =
  process.env.NEXT_PUBLIC_SALES_PHONE_TEL ?? SALES_PHONE_DISPLAY.replace(/[^\d+]/g, '')

const ENTERPRISE_PLAN: Plan = {
  tier: 'enterprise',
  name: 'Enterprise',
  amount: 0,
  currency: 'INR',
  period: 'custom',
  features: [
    'Custom seats and installer slots',
    'Custom compile credits',
    'Custom Human Edit pool',
    'Dedicated onboarding and support',
    'Security review and procurement support',
  ],
}

const METER_CONFIGS: UsageMeterConfig[] = [
  {
    key: 'seats',
    label: 'Seats',
    description: 'Workspace members',
    icon: Users,
  },
  {
    key: 'installer_slots',
    label: 'Installer Slots',
    description: 'Hosted plugin installers',
    icon: PackageCheck,
  },
  {
    key: 'compile_credits',
    label: 'Compile Credits',
    description: 'Fresh workflow compiles',
    icon: Code2,
  },
  {
    key: 'human_edit_tokens',
    label: 'Human Edit Pool',
    description: 'LLM-assisted recovery and edits',
    icon: Wand2,
  },
]

function normalizePlan(plan?: string | null) {
  const tier = (plan || 'free').toLowerCase()
  return tier === 'basic' ? 'starter' : tier
}

function displayPlanName(plan?: string | null) {
  const normalized = normalizePlan(plan)
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function formatPrice(plan: Plan) {
  if (normalizePlan(plan.tier) === 'enterprise') return 'Custom'
  if (!plan.amount) return 'Free'
  const currency = (plan.currency || 'INR').toUpperCase()
  const symbol = currency === 'INR' ? '₹' : `${currency} `
  return `${symbol}${plan.amount.toLocaleString()}`
}

function formatPeriod(plan: Plan) {
  if (normalizePlan(plan.tier) === 'enterprise') return 'contract'
  if (!plan.amount) return 'forever'
  return plan.period || 'month'
}

function formatDate(value?: string | null) {
  if (!value) return 'Not scheduled'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Not scheduled'
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatUnixDate(value?: number | null) {
  if (!value) return 'Not scheduled'
  return formatDate(new Date(value * 1000).toISOString())
}

function formatCompactNumber(value?: number | null) {
  if (value == null) return 'Unlimited'
  return new Intl.NumberFormat(undefined, {
    notation: Math.abs(value) >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value)
}

function formatMeterValue(value?: number | null, key?: EntitlementMeterKey) {
  if (value == null) return 'Unlimited'
  if (key === 'human_edit_tokens') return formatCompactNumber(value)
  return value.toLocaleString()
}

function meterPercent(meter?: EntitlementMeter) {
  if (!meter || meter.unlimited || !meter.limit) return 0
  return Math.min(100, Math.round((meter.used / meter.limit) * 100))
}

function meterTone(meter?: EntitlementMeter) {
  if (!meter || meter.unlimited || !meter.limit) return 'neutral'
  const percent = meterPercent(meter)
  if (percent >= 100) return 'danger'
  if (percent >= 80) return 'warning'
  return 'healthy'
}

function checkoutLabel(status: CheckoutStatus) {
  if (status === 'ready') return 'Checkout ready'
  if (status === 'failed') return 'Checkout unavailable'
  if (status === 'missing_key') return 'Checkout key missing'
  return 'Checkout loading'
}

function checkoutBadgeClass(status: CheckoutStatus) {
  if (status === 'ready') return 'border-cyan-400/25 bg-white/[0.03] text-cyan-300'
  if (status === 'failed' || status === 'missing_key') return 'border-amber-500/40 bg-amber-500/10 text-amber-200'
  return 'border-white/8 bg-white/[0.03] text-zinc-400'
}

export function BillingPage() {
  const queryClient = useQueryClient()
  const [checkoutStatus, setCheckoutStatus] = useState<CheckoutStatus>(
    RAZORPAY_KEY_ID ? 'loading' : 'missing_key',
  )
  const [processingTier, setProcessingTier] = useState<string | null>(null)
  const [currentPlanOverride, setCurrentPlanOverride] = useState<string | null>(null)

  const plansQuery = useQuery({
    queryKey: ['billing-plans'],
    queryFn: listPlans,
  })
  const subscriptionQuery = useQuery({
    queryKey: ['subscription'],
    queryFn: fetchSubscription,
  })
  const entitlementsQuery = useQuery({
    queryKey: ['entitlements'],
    queryFn: fetchEntitlements,
  })

  useEffect(() => {
    if (!RAZORPAY_KEY_ID) {
      setCheckoutStatus('missing_key')
      return
    }

    if (window.Razorpay) {
      setCheckoutStatus('ready')
      return
    }

    const existingScript = document.querySelector<HTMLScriptElement>(
      `script[src="${RAZORPAY_CHECKOUT_SRC}"]`,
    )

    const handleLoad = () => setCheckoutStatus('ready')
    const handleError = () => setCheckoutStatus('failed')

    if (existingScript) {
      existingScript.addEventListener('load', handleLoad)
      existingScript.addEventListener('error', handleError)
      return () => {
        existingScript.removeEventListener('load', handleLoad)
        existingScript.removeEventListener('error', handleError)
      }
    }

    const script = document.createElement('script')
    script.src = RAZORPAY_CHECKOUT_SRC
    script.async = true
    script.addEventListener('load', handleLoad)
    script.addEventListener('error', handleError)
    document.body.appendChild(script)

    return () => {
      script.removeEventListener('load', handleLoad)
      script.removeEventListener('error', handleError)
    }
  }, [])

  const plans = useMemo(() => {
    const remotePlans = plansQuery.data?.plans ?? []
    const hasEnterprise = remotePlans.some((plan) => normalizePlan(plan.tier) === 'enterprise')
    const visiblePlans = hasEnterprise ? remotePlans : [...remotePlans, ENTERPRISE_PLAN]
    return [...visiblePlans].sort((a, b) => {
      const order = ['free', 'starter', 'pro', 'enterprise']
      return order.indexOf(normalizePlan(a.tier)) - order.indexOf(normalizePlan(b.tier))
    })
  }, [plansQuery.data?.plans])

  const subscription = subscriptionQuery.data?.subscription
  const entitlements = entitlementsQuery.data
  const currentPlan = normalizePlan(
    currentPlanOverride ?? subscription?.plan ?? entitlements?.plan ?? 'free',
  )
  const hasError = plansQuery.isError || subscriptionQuery.isError || entitlementsQuery.isError
  const canCheckout = checkoutStatus === 'ready'

  async function refreshBilling() {
    await Promise.all([
      plansQuery.refetch(),
      subscriptionQuery.refetch(),
      entitlementsQuery.refetch(),
    ])
    toast.success('Billing data refreshed')
  }

  async function subscribe(tier: string) {
    const normalizedTier = normalizePlan(tier)

    if (normalizedTier !== 'starter' && normalizedTier !== 'pro') {
      toast.info('This plan does not require checkout.')
      return
    }

    if (!RAZORPAY_KEY_ID) {
      toast.error('Razorpay checkout key is not configured.')
      return
    }

    if (!canCheckout) {
      toast.error('Razorpay checkout is not ready yet.')
      return
    }

    setProcessingTier(normalizedTier)
    try {
      const order = await createRazorpaySubscription(normalizedTier)
      const Razorpay = window.Razorpay
      if (!Razorpay) {
        setCheckoutStatus('failed')
        setProcessingTier(null)
        toast.error('Razorpay checkout is not available.')
        return
      }

      const checkout = new Razorpay({
        key: RAZORPAY_KEY_ID,
        subscription_id: order.subscription_id,
        name: 'Conxa',
        description: `Conxa ${displayPlanName(normalizedTier)} plan`,
        handler: async (response) => {
          try {
            await verifyRazorpaySubscription(
              response.razorpay_payment_id,
              response.razorpay_subscription_id,
              response.razorpay_signature,
            )
            setCurrentPlanOverride(normalizedTier)
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ['subscription'] }),
              queryClient.invalidateQueries({ queryKey: ['entitlements'] }),
            ])
            toast.success('Subscription activated')
          } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Payment verification failed')
          } finally {
            setProcessingTier(null)
          }
        },
        modal: {
          ondismiss: () => {
            setProcessingTier(null)
            toast.info('Checkout closed')
          },
        },
        theme: {
          color: '#2563eb',
        },
      })

      checkout.open()
    } catch (error) {
      setProcessingTier(null)
      toast.error(error instanceof Error ? error.message : 'Subscription could not be started')
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-[#0b0d10]">
      <PageHeader
        title="Billing"
        description="Plans, usage, and payment controls for this workspace."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={checkoutBadgeClass(checkoutStatus)} variant="outline">
              <CreditCard className="mr-1.5 h-3.5 w-3.5" />
              {checkoutLabel(checkoutStatus)}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              className="cursor-pointer border-white/8 bg-white/[0.03] text-zinc-200 hover:bg-white/[0.06] disabled:cursor-not-allowed"
              onClick={refreshBilling}
              disabled={plansQuery.isFetching || subscriptionQuery.isFetching || entitlementsQuery.isFetching}
            >
              <RefreshCw
                className={`mr-2 h-4 w-4 ${
                  plansQuery.isFetching || subscriptionQuery.isFetching || entitlementsQuery.isFetching
                    ? 'animate-spin'
                    : ''
                }`}
              />
              Refresh
            </Button>
          </div>
        }
      />

      <main className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6">
        {hasError ? (
          <BillingErrorBanner
            onRetry={refreshBilling}
            loading={
              plansQuery.isFetching || subscriptionQuery.isFetching || entitlementsQuery.isFetching
            }
          />
        ) : null}

        <section className="space-y-2.5">
          <div className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">Workspace Usage</h2>
              <p className="text-xs text-zinc-500">
                Customer-visible meters for the current UTC billing period.
              </p>
            </div>
            <Badge variant="outline" className="w-fit border-white/8 bg-white/[0.03] px-1.5 py-0 text-[10px] text-zinc-400">
              {entitlements?.workspace_id ? `Workspace ${entitlements.workspace_id}` : 'Workspace loading'}
            </Badge>
          </div>
          <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
            {METER_CONFIGS.map((config) => (
              <UsageMeterCard
                key={config.key}
                config={config}
                meter={entitlements?.meters?.[config.key]}
                loading={entitlementsQuery.isLoading}
              />
            ))}
          </div>
        </section>

        <section className="space-y-2.5">
          <div className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">Subscription Plans</h2>
              <p className="text-xs text-zinc-500">
                Upgrade limits without changing local plugin or workflow creation.
              </p>
            </div>
            <Badge variant="outline" className="w-fit border-white/8 bg-black/20 px-1.5 py-0 text-[10px] text-zinc-400">
              Legacy Basic displays as Starter
            </Badge>
          </div>

          {plansQuery.isLoading ? (
            <PlanSkeletonGrid />
          ) : (
            <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
              {plans.map((plan) => (
                <PlanCard
                  key={plan.tier}
                  plan={plan}
                  currentPlan={currentPlan}
                  checkoutStatus={checkoutStatus}
                  processingTier={processingTier}
                  onSubscribe={subscribe}
                />
              ))}
            </div>
          )}
        </section>

        <PaymentOperationsPanel
          checkoutStatus={checkoutStatus}
          currentPlan={currentPlan}
          resetAt={entitlements?.reset_at}
          currentPeriodEnd={subscription?.current_period_end}
        />
      </main>
    </div>
  )
}

function UsageMeterCard({
  config,
  meter,
  loading,
}: {
  config: UsageMeterConfig
  meter?: EntitlementMeter
  loading?: boolean
}) {
  const Icon = config.icon
  const percent = meterPercent(meter)
  const tone = meterTone(meter)
  const progressClass =
    tone === 'danger'
      ? 'bg-red-500'
      : tone === 'warning'
        ? 'bg-amber-400'
        : 'bg-cyan-400/80'
  const statusLabel =
    tone === 'danger' ? 'Exhausted' : tone === 'warning' ? 'Near limit' : meter?.unlimited ? 'Unlimited' : 'Available'

  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardContent className="min-h-[8.2rem] p-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-white">{config.label}</p>
            <p className="mt-0.5 text-[11px] text-zinc-600">{config.description}</p>
          </div>
          <div className="rounded-md border border-white/8 bg-white/[0.03] p-1.5 text-zinc-400">
            <Icon className="h-3.5 w-3.5" />
          </div>
        </div>

        {loading ? (
          <div className="mt-3 space-y-2">
            <div className="h-6 w-28 animate-pulse rounded bg-white/8" />
            <div className="h-1.5 w-full animate-pulse rounded bg-white/8" />
          </div>
        ) : (
          <>
            <div className="mt-3 flex items-end justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xl font-semibold leading-none text-white">
                  {formatMeterValue(meter?.used ?? 0, config.key)}
                </p>
                <p className="mt-1 text-[11px] text-zinc-600">
                  of {formatMeterValue(meter?.limit, config.key)} used
                </p>
              </div>
              <Badge
                variant="outline"
                className={
                  tone === 'danger'
                    ? 'border-red-500/40 bg-red-500/10 px-1.5 py-0 text-[10px] text-red-200'
                    : tone === 'warning'
                      ? 'border-amber-500/40 bg-amber-500/10 px-1.5 py-0 text-[10px] text-amber-200'
                      : 'border-cyan-400/30 bg-white/[0.03] px-1.5 py-0 text-[10px] text-cyan-300'
                }
              >
                {statusLabel}
              </Badge>
            </div>
            <div className="mt-2.5 h-1.5 rounded-full bg-white/8">
              <div
                className={`h-1.5 rounded-full transition-all ${progressClass}`}
                style={{ width: meter?.unlimited ? '100%' : `${percent}%` }}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-zinc-600">
              <span>{meter?.unlimited ? 'No cap' : `${percent}% used`}</span>
              <span>{formatMeterValue(meter?.remaining, config.key)} remaining</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function PlanCard({
  plan,
  currentPlan,
  checkoutStatus,
  processingTier,
  onSubscribe,
}: {
  plan: Plan
  currentPlan: string
  checkoutStatus: CheckoutStatus
  processingTier: string | null
  onSubscribe: (tier: string) => void
}) {
  const [contactOpen, setContactOpen] = useState(false)
  const tier = normalizePlan(plan.tier)
  const isCurrent = tier === currentPlan
  const isRecommended = tier === 'starter'
  const isEnterprise = tier === 'enterprise'
  const isPaidCheckoutPlan = tier === 'starter' || tier === 'pro'
  const isProcessing = processingTier === tier
  const checkoutBlocked = isPaidCheckoutPlan && checkoutStatus !== 'ready'
  const disabled =
    isCurrent ||
    tier === 'free' ||
    (!isPaidCheckoutPlan && !isEnterprise) ||
    checkoutBlocked ||
    Boolean(processingTier)

  let buttonLabel = isCurrent ? 'Current plan' : `Choose ${displayPlanName(tier)}`
  if (tier === 'free' && !isCurrent) buttonLabel = 'Free plan'
  if (isEnterprise) buttonLabel = 'Contact us'
  if (checkoutBlocked) buttonLabel = checkoutLabel(checkoutStatus)
  if (isProcessing) buttonLabel = 'Opening checkout'

  return (
    <>
      <Card
        className={`flex min-h-[22.75rem] flex-col border shadow-none ${
          isEnterprise
            ? 'border-cyan-400/25 bg-white/[0.025]'
            : isRecommended
              ? 'border-cyan-400/25 bg-white/[0.025]'
              : isCurrent
                ? 'border-emerald-500/30 bg-white/[0.025]'
                : 'border-white/8 bg-white/[0.025]'
        }`}
      >
        <CardHeader className="p-3.5 pb-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base text-white">{plan.name || displayPlanName(tier)}</CardTitle>
              <p className="mt-0.5 text-xs text-zinc-500">{displayPlanName(tier)} workspace limits</p>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              {isCurrent ? (
                <Badge className="border-emerald-500/30 bg-white/[0.03] text-emerald-300" variant="outline">
                  Current
                </Badge>
              ) : null}
              {isRecommended && !isCurrent ? (
                <Badge className="border-cyan-400/30 bg-white/[0.03] text-cyan-300" variant="outline">
                  Recommended
                </Badge>
              ) : null}
              {isEnterprise && !isCurrent ? (
                <Badge className="border-teal-300/30 bg-white/[0.03] text-teal-300" variant="outline">
                  Custom
                </Badge>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-1 flex-col p-3.5 pt-0">
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-semibold text-white">{formatPrice(plan)}</span>
              <span className="text-xs text-zinc-600">/ {formatPeriod(plan)}</span>
            </div>
          </div>

          <div className="mt-3 space-y-1.5">
            {(plan.features || []).slice(0, 7).map((feature) => (
              <div key={feature} className="flex gap-2 text-xs text-zinc-300">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-300" />
                <span>{feature}</span>
              </div>
            ))}
          </div>

          <div className="mt-auto pt-3">
            {isEnterprise && !isCurrent ? (
              <Button
                className="h-8 w-full cursor-pointer border border-cyan-400/30 bg-white/[0.04] text-cyan-200 hover:bg-white/[0.06]"
                onClick={() => setContactOpen(true)}
              >
                <Mail className="mr-2 h-4 w-4" />
                {buttonLabel}
              </Button>
            ) : (
              <Button
                className={`h-8 w-full disabled:cursor-not-allowed ${
                  disabled
                    ? ''
                    : isRecommended
                      ? 'cursor-pointer border border-cyan-400/30 bg-white/[0.04] text-cyan-200 hover:bg-white/[0.06]'
                      : 'cursor-pointer border-white/8 bg-white/[0.03] text-zinc-200 hover:bg-white/[0.06]'
                }`}
                variant={isRecommended && !disabled ? 'default' : 'outline'}
                disabled={disabled}
                onClick={() => onSubscribe(tier)}
              >
                {isProcessing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {buttonLabel}
              </Button>
            )}
            {checkoutBlocked ? (
              <p className="mt-2 text-xs text-amber-300">
                Configure Razorpay checkout before paid plan activation.
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>
      {isEnterprise ? (
        <EnterpriseContactDialog open={contactOpen} onOpenChange={setContactOpen} />
      ) : null}
    </>
  )
}

function EnterpriseContactDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-white/10 bg-[#0d0f12] p-0 text-zinc-100 sm:max-w-md">
        <DialogHeader className="border-b border-white/8 px-4 py-3 text-left">
          <DialogTitle className="text-white">Contact Conxa</DialogTitle>
          <DialogDescription className="text-zinc-500">
            Use either channel for Enterprise pricing, custom limits, and procurement.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2.5 px-4 py-4">
          <a
            className="flex items-center gap-3 rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-200 transition-colors hover:border-cyan-400/30 hover:text-cyan-300"
            href={`mailto:${SALES_EMAIL}?subject=Conxa%20Enterprise%20plan&body=Hi%20Conxa%20team%2C%0A%0AI%20want%20to%20talk%20about%20an%20Enterprise%20plan.`}
          >
            <span className="rounded-md border border-white/8 bg-white/[0.03] p-1.5 text-cyan-300">
              <Mail className="h-3.5 w-3.5" />
            </span>
            <span className="min-w-0">
              <span className="block text-xs text-zinc-500">Email</span>
              <span className="block truncate font-medium">{SALES_EMAIL}</span>
            </span>
          </a>
          <a
            className="flex items-center gap-3 rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-200 transition-colors hover:border-cyan-400/30 hover:text-cyan-300"
            href={`tel:${SALES_PHONE_TEL}`}
          >
            <span className="rounded-md border border-white/8 bg-white/[0.03] p-1.5 text-cyan-300">
              <PhoneCall className="h-3.5 w-3.5" />
            </span>
            <span className="min-w-0">
              <span className="block text-xs text-zinc-500">Phone</span>
              <span className="block truncate font-medium">{SALES_PHONE_DISPLAY}</span>
            </span>
          </a>
        </div>
        <div className="flex justify-end border-t border-white/8 bg-white/[0.03] px-4 py-3">
          <DialogClose asChild>
            <Button
              variant="outline"
              className="h-8 cursor-pointer border-white/8 bg-black/20 text-zinc-200 hover:bg-white/[0.06]"
            >
              Close
            </Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function PaymentOperationsPanel({
  checkoutStatus,
  currentPlan,
  resetAt,
  currentPeriodEnd,
}: {
  checkoutStatus: CheckoutStatus
  currentPlan: string
  resetAt?: string | null
  currentPeriodEnd?: number | null
}) {
  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/8 p-3.5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base text-white">Billing Operations</CardTitle>
            <p className="mt-0.5 text-xs text-zinc-500">Payment readiness and account timing.</p>
          </div>
          <div className="rounded-md border border-white/8 bg-black/20 p-1.5 text-zinc-400">
            <CreditCard className="h-3.5 w-3.5" />
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2.5 p-3.5 lg:grid-cols-[minmax(0,1.1fr)_minmax(18rem,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-md border border-white/8 bg-black/20 p-2.5">
          <p className="text-xs font-medium uppercase tracking-normal text-zinc-500">Checkout</p>
          <div className="mt-1.5 flex items-center gap-2">
            {checkoutStatus === 'ready' ? (
              <CheckCircle2 className="h-4 w-4 text-cyan-300" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-300" />
            )}
            <span className="text-sm font-medium text-white">{checkoutLabel(checkoutStatus)}</span>
          </div>
          <p className="mt-1.5 text-xs text-zinc-500">
            Paid plan actions use Razorpay Checkout. Workspace meters remain readable even when checkout is not configured.
          </p>
        </div>

        <div className="rounded-md border border-white/8 bg-black/20 p-2.5">
          <p className="text-xs font-medium uppercase tracking-normal text-zinc-500">Account Timing</p>
          <div className="mt-2 grid gap-2">
            <InfoRow label="Active plan" value={displayPlanName(currentPlan)} />
            <InfoRow label="Usage reset" value={formatDate(resetAt)} />
            <InfoRow label="Billing period end" value={formatUnixDate(currentPeriodEnd)} />
          </div>
        </div>

        <div className="rounded-md border border-white/8 bg-black/20 p-2.5">
          <p className="text-sm font-medium text-cyan-300">Metering policy</p>
          <p className="mt-1.5 text-xs text-zinc-500">
            Plugin creation and workflow recording stay unlimited. Only seats, installer slots, compile credits, and Human Edit pool are customer-visible meters.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/8 pb-2 last:border-b-0 last:pb-0">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="truncate text-right text-xs font-medium text-zinc-200">{value}</span>
    </div>
  )
}

function BillingErrorBanner({ onRetry, loading }: { onRetry: () => void; loading?: boolean }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-300" />
        <div>
          <p className="font-medium text-red-100">Billing data could not be loaded.</p>
          <p className="mt-1 text-sm text-red-100/75">
            Retry after confirming the cloud backend is running and reachable.
          </p>
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="w-fit cursor-pointer border-red-400/40 bg-transparent text-red-100 hover:bg-red-500/10 disabled:cursor-not-allowed"
        onClick={onRetry}
        disabled={loading}
      >
        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
        Retry
      </Button>
    </div>
  )
}

function PlanSkeletonGrid() {
  return (
    <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((item) => (
        <Card key={item} className="min-h-[22.75rem] border-white/8 bg-black/20 shadow-none">
          <CardContent className="p-3.5">
            <div className="h-4 w-20 animate-pulse rounded bg-white/8" />
            <div className="mt-4 h-7 w-28 animate-pulse rounded bg-white/8" />
            <div className="mt-5 space-y-2">
              <div className="h-3.5 w-full animate-pulse rounded bg-white/8" />
              <div className="h-3.5 w-5/6 animate-pulse rounded bg-white/8" />
              <div className="h-3.5 w-4/6 animate-pulse rounded bg-white/8" />
              <div className="h-3.5 w-3/4 animate-pulse rounded bg-white/8" />
            </div>
            <div className="mt-5 h-8 w-full animate-pulse rounded bg-white/8" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
