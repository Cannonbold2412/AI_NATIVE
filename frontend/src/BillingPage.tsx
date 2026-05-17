'use client'

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { listPlans, createRazorpaySubscription, verifyRazorpaySubscription, type Plan } from '@/api/razorpayApi'
import { fetchSubscription } from '@/api/productApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CreditCard, CheckCircle } from 'lucide-react'

declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Razorpay: new (options: Record<string, any>) => { open(): void }
  }
}

export function BillingPage() {
  const queryClient = useQueryClient()
  const [plans, setPlans] = useState<Plan[]>([])
  const [currentPlan, setCurrentPlan] = useState<string>('free')
  const [rzpReady, setRzpReady] = useState(false)
  const [loading, setLoading] = useState(false)
  const [processingTier, setProcessingTier] = useState<string | null>(null)
  const scriptRef = useRef<HTMLScriptElement | null>(null)

  useEffect(() => {
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.async = true
    script.onload = () => setRzpReady(true)
    script.onerror = () => toast.error('Failed to load Razorpay checkout')
    document.body.appendChild(script)
    scriptRef.current = script
    return () => {
      if (scriptRef.current) document.body.removeChild(scriptRef.current)
    }
  }, [])

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true)
        const [plansResp, subResp] = await Promise.all([listPlans(), fetchSubscription()])
        setPlans(plansResp.plans)
        setCurrentPlan(subResp.subscription?.plan || 'free')
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to load billing data')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [])

  async function subscribe(tier: string) {
    if (tier === 'free') {
      toast.info('Free plan is already active')
      return
    }
    setProcessingTier(tier)
    try {
      const order = await createRazorpaySubscription(tier as 'basic' | 'pro')
      const keyId = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID ?? ''
      const rzp = new window.Razorpay({
        key: keyId,
        subscription_id: order.subscription_id,
        name: 'Conxa',
        description: `Conxa ${tier.charAt(0).toUpperCase() + tier.slice(1)} Plan`,
        handler: async (response: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) => {
          try {
            await verifyRazorpaySubscription(
              response.razorpay_payment_id,
              response.razorpay_subscription_id,
              response.razorpay_signature,
            )
            toast.success(`Subscribed to ${tier} plan!`)
            setCurrentPlan(tier)
            queryClient.invalidateQueries({ queryKey: ['subscription'] })
          } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Payment verification failed')
          }
        },
        modal: {
          ondismiss: () => toast.info('Subscription cancelled'),
        },
        theme: { color: '#0ea5e9' },
      })
      rzp.open()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not initiate subscription')
    } finally {
      setProcessingTier(null)
    }
  }

  return (
    <AppShell title="Billing" description="Choose your plan and manage your subscription." mainClassName="overflow-y-auto">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-4 sm:px-6">
        <div>
          <h2 className="mb-1 text-lg font-semibold text-white">Subscription Plans</h2>
          <p className="text-sm text-zinc-400">Choose a plan that fits your needs. Cancel or upgrade anytime.</p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <p className="text-zinc-400">Loading plans...</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-3">
            {plans.map((plan) => {
              const isActive = currentPlan === plan.tier
              return (
                <Card
                  key={plan.tier}
                  className={`relative flex flex-col border ${
                    isActive ? 'border-sky-500 bg-sky-500/5' : 'border-white/10 bg-white/[0.03]'
                  } shadow-none`}
                >
                  {isActive && (
                    <div className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-sky-500/20 px-3 py-1">
                      <CheckCircle className="size-3 text-sky-400" />
                      <span className="text-xs font-semibold text-sky-400">Current</span>
                    </div>
                  )}
                  <CardHeader className="border-b border-white/8">
                    <CardTitle className="text-white">{plan.name}</CardTitle>
                    <div className="mt-2 flex items-baseline gap-1">
                      <span className="text-3xl font-bold text-white">₹{plan.amount}</span>
                      {plan.period && <span className="text-sm text-zinc-400">/{plan.period}</span>}
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col gap-4 p-4">
                    <ul className="space-y-2">
                      {plan.features.length > 0 ? (
                        plan.features.map((feature, idx) => (
                          <li key={idx} className="flex items-start gap-2 text-sm text-zinc-300">
                            <span className="mt-1 inline-block h-1.5 w-1.5 rounded-full bg-sky-400 flex-shrink-0" />
                            {feature}
                          </li>
                        ))
                      ) : (
                        <li className="text-sm text-zinc-400">Forever free</li>
                      )}
                    </ul>
                    <Button
                      onClick={() => void subscribe(plan.tier)}
                      disabled={isActive || !rzpReady || processingTier === plan.tier}
                      className="mt-auto w-full"
                      variant={isActive ? 'outline' : 'default'}
                    >
                      {isActive ? (
                        <>
                          <CheckCircle className="size-4" />
                          Current Plan
                        </>
                      ) : processingTier === plan.tier ? (
                        'Processing…'
                      ) : (
                        <>
                          <CreditCard className="size-4" />
                          Subscribe Now
                        </>
                      )}
                    </Button>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}

        <div className="rounded-lg border border-blue-900/30 bg-blue-950/20 p-4">
          <p className="text-sm text-blue-200">
            💡 <strong>Tip:</strong> All plans include our core features. Cancel anytime without penalty.
          </p>
        </div>
      </div>
    </AppShell>
  )
}
