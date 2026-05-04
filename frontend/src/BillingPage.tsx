'use client'

import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createCheckout, createPortal, fetchSubscription, fetchUsage } from '@/api/productApi'
import { AppShell } from '@/components/layout/AppLayout'
import { ErrorState, LoadingState, StatCard, StatusBadge, UsageMeter } from '@/components/product/ProductPrimitives'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CreditCard, ExternalLink } from 'lucide-react'

export function BillingPage() {
  const subscriptionQ = useQuery({ queryKey: ['subscription'], queryFn: fetchSubscription })
  const usageQ = useQuery({ queryKey: ['usage'], queryFn: fetchUsage })
  const subscription = subscriptionQ.data?.subscription

  async function go(kind: 'checkout' | 'portal') {
    try {
      const result = kind === 'checkout' ? await createCheckout() : await createPortal()
      window.location.assign(result.url)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Billing redirect failed')
    }
  }

  return (
    <AppShell title="Billing" description="Plan, usage, subscription status, checkout, and customer portal." mainClassName="overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-4 sm:px-6">
        {subscriptionQ.isLoading ? <LoadingState label="Loading billing" /> : null}
        {subscriptionQ.isError ? <ErrorState message={(subscriptionQ.error as Error).message} /> : null}
        {subscription ? (
          <>
            <section className="grid gap-3 sm:grid-cols-3">
              <StatCard label="Plan" value={subscription.plan} />
              <StatCard label="Status" value={<StatusBadge status={subscription.status} />} />
              <StatCard label="Stripe" value={subscription.stripe_configured ? 'Configured' : 'Local'} tone={subscription.stripe_configured ? 'good' : 'warn'} />
            </section>
            <Card className="border-white/8 bg-white/[0.03] shadow-none">
              <CardHeader className="border-b border-white/8">
                <CardTitle className="flex items-center gap-2 text-white">
                  <CreditCard className="size-4 text-sky-300" />
                  Subscription controls
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2 p-4">
                <Button onClick={() => void go('checkout')} disabled={!subscription.stripe_configured}>
                  <ExternalLink className="size-4" />
                  Start checkout
                </Button>
                <Button variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-200" onClick={() => void go('portal')} disabled={!subscription.customer_id}>
                  <ExternalLink className="size-4" />
                  Open portal
                </Button>
              </CardContent>
            </Card>
          </>
        ) : null}
        {usageQ.data ? (
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="text-white">Usage</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 p-4">
              <UsageMeter label="Skills" value={usageQ.data.skills} limit={usageQ.data.limits.skills} />
              <UsageMeter label="Packages" value={usageQ.data.packages} limit={usageQ.data.limits.packages} />
              <UsageMeter label="Jobs" value={usageQ.data.jobs} limit={null} />
            </CardContent>
          </Card>
        ) : null}
      </div>
    </AppShell>
  )
}
