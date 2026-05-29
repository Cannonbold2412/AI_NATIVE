import { LenisProvider } from '@/components/marketing/LenisProvider'
import { MarketingNav } from '@/components/marketing/MarketingNav'
import { MarketingFooter } from '@/components/marketing/MarketingFooter'

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <LenisProvider>
      <MarketingNav />
      <main>{children}</main>
      <MarketingFooter />
    </LenisProvider>
  )
}
