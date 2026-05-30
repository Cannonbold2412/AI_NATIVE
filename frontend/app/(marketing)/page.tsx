import { Hero } from '@/components/marketing/hero/Hero'
import { TrustedWorkflows } from '@/components/marketing/sections/TrustedWorkflows'
import { ValueGrid } from '@/components/marketing/value/ValueGrid'
import { Pipeline } from '@/components/marketing/sections/Pipeline'
import { GovSaas } from '@/components/marketing/sections/GovSaas'
import { RecoveryLayers } from '@/components/marketing/sections/RecoveryLayers'
import { ObservableRuntime } from '@/components/marketing/sections/ObservableRuntime'
import { AnalyticsDashboard } from '@/components/marketing/sections/AnalyticsDashboard'
import { InternalEnterprise } from '@/components/marketing/sections/InternalEnterprise'
import { Reliability } from '@/components/marketing/sections/Reliability'
import { Cta } from '@/components/marketing/sections/Cta'

export default function MarketingPage() {
  return (
    <>
      <Hero />
      <TrustedWorkflows />
      <ValueGrid />
      <Pipeline />
      <GovSaas />
      <RecoveryLayers />
      <ObservableRuntime />
      <AnalyticsDashboard />
      <InternalEnterprise />
      <Reliability />
      <Cta />
    </>
  )
}
