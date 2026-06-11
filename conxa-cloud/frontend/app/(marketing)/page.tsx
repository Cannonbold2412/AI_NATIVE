import type { Metadata } from 'next'
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
import { createPublicPageMetadata } from '@/lib/siteMetadata'

export const metadata: Metadata = createPublicPageMetadata({
  title: 'CONXA',
  description:
    'Conxa turns recorded browser workflows into local MCP skills for Claude Desktop automation and reliable software operation.',
  path: '/',
})

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
