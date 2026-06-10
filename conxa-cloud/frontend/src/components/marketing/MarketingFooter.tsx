import Link from 'next/link'

export function MarketingFooter() {
  return (
    <footer className="border-t border-white/6 bg-[#06080b] px-6 py-12">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-10 sm:flex-row sm:items-start sm:justify-between">
          {/* Brand */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <div
                className="flex h-7 w-7 items-center justify-center rounded-lg"
                style={{ background: 'linear-gradient(135deg, #22d3ee, #5eead4)' }}
              >
                <span className="text-[11px] font-bold text-[#06080b]">C</span>
              </div>
              <span className="text-sm font-semibold text-white">CONXA</span>
            </div>
            <p className="max-w-xs text-xs leading-relaxed text-[#6b7280]">
              AI operational runtime. Operate software by talking.
            </p>
          </div>

          {/* Links */}
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            <div className="flex flex-col gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Product</p>
              <Link href="/#pipeline" className="text-sm text-[#9ba3af] hover:text-white">How it works</Link>
              <Link href="/#recovery" className="text-sm text-[#9ba3af] hover:text-white">Recovery system</Link>
              <Link href="/#observability" className="text-sm text-[#9ba3af] hover:text-white">Observability</Link>
              <Link href="/docs" className="text-sm text-[#9ba3af] hover:text-white">Docs</Link>
              <Link href="/sign-up" className="text-sm text-[#9ba3af] hover:text-white">Get started</Link>
            </div>
            <div className="flex flex-col gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Company</p>
              <Link href="/docs/support" className="text-sm text-[#9ba3af] hover:text-white">Contact</Link>
              <Link href="/sign-in" className="text-sm text-[#9ba3af] hover:text-white">Sign in</Link>
            </div>
            <div className="flex flex-col gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Legal</p>
              <Link href="/docs/security" className="text-sm text-[#9ba3af] hover:text-white">Security</Link>
              <Link href="/docs/privacy" className="text-sm text-[#9ba3af] hover:text-white">Privacy</Link>
              <Link href="/docs/terms" className="text-sm text-[#9ba3af] hover:text-white">Terms</Link>
              <Link href="/docs/billing" className="text-sm text-[#9ba3af] hover:text-white">Billing</Link>
            </div>
          </div>
        </div>

        <div className="mt-10 flex flex-col items-start justify-between gap-4 border-t border-white/6 pt-8 sm:flex-row sm:items-center">
          <p className="text-xs text-[#6b7280]">© {new Date().getFullYear()} CONXA. All rights reserved.</p>
          <p className="text-xs text-[#6b7280]">
            Powered by{' '}
            <span className="text-[#9ba3af]">Claude</span>
          </p>
        </div>
      </div>
    </footer>
  )
}
