'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { GlowButton } from './primitives/GlowButton'

const links = [
  { label: 'How it works', href: '#pipeline' },
  { label: 'Recovery', href: '#recovery' },
  { label: 'Observability', href: '#observability' },
  { label: 'Enterprise', href: '#enterprise' },
]

export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <motion.header
      className="fixed top-0 z-50 w-full transition-all duration-500"
      animate={{
        backgroundColor: scrolled ? 'rgba(6,8,11,0.92)' : 'rgba(6,8,11,0)',
        backdropFilter: scrolled ? 'blur(16px)' : 'blur(0px)',
        borderBottomColor: scrolled ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0)',
      }}
      style={{ borderBottomWidth: 1, borderBottomStyle: 'solid' }}
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="relative flex h-8 w-8 items-center justify-center rounded-lg overflow-hidden">
            <div
              className="absolute inset-0 opacity-80 group-hover:opacity-100 transition-opacity"
              style={{ background: 'linear-gradient(135deg, #22d3ee, #5eead4)' }}
            />
            <span className="relative text-xs font-bold text-[#06080b]">C</span>
          </div>
          <span className="text-base font-semibold tracking-tight text-white">CONXA</span>
        </Link>

        {/* Desktop links */}
        <nav className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <a
              key={l.label}
              href={l.href}
              className="text-sm text-[#9ba3af] transition-colors hover:text-white"
            >
              {l.label}
            </a>
          ))}
        </nav>

        {/* CTA */}
        <div className="hidden items-center gap-3 md:flex">
          <Link
            href="/sign-in"
            className="text-sm text-[#9ba3af] transition-colors hover:text-white"
          >
            Sign in
          </Link>
          <GlowButton href="/sign-up">Get started</GlowButton>
        </div>

        {/* Mobile hamburger */}
        <button
          className="flex md:hidden flex-col gap-1.5 p-1"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label="Toggle menu"
        >
          <span className={`block h-0.5 w-5 bg-white transition-transform ${mobileOpen ? 'translate-y-2 rotate-45' : ''}`} />
          <span className={`block h-0.5 w-5 bg-white transition-opacity ${mobileOpen ? 'opacity-0' : ''}`} />
          <span className={`block h-0.5 w-5 bg-white transition-transform ${mobileOpen ? '-translate-y-2 -rotate-45' : ''}`} />
        </button>
      </div>

      {/* Mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-white/6 bg-[#06080b]/95 backdrop-blur-xl"
          >
            <div className="flex flex-col gap-1 px-6 py-4">
              {links.map((l) => (
                <a
                  key={l.label}
                  href={l.href}
                  className="py-2 text-sm text-[#9ba3af] hover:text-white"
                  onClick={() => setMobileOpen(false)}
                >
                  {l.label}
                </a>
              ))}
              <div className="mt-4 flex flex-col gap-2">
                <Link href="/sign-in" className="py-2 text-sm text-[#9ba3af] hover:text-white">
                  Sign in
                </Link>
                <GlowButton href="/sign-up">Get started</GlowButton>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  )
}
