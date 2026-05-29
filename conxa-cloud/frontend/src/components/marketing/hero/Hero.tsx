'use client'

import { motion } from 'framer-motion'
import { GradientMesh } from '../GradientMesh'
import { GridBackground } from '../GridBackground'
import { GlowButton } from '../primitives/GlowButton'
import { ChatPanel } from './ChatPanel'
import { BrowserSim } from './BrowserSim'

export function Hero() {
  return (
    <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#06080b] px-6 pb-20 pt-32 lg:pt-28">
      <GradientMesh />
      <GridBackground />

      {/* Badge */}
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="mb-8 inline-flex items-center gap-2 rounded-full border border-[rgba(34,211,238,0.2)] bg-[rgba(34,211,238,0.06)] px-4 py-1.5"
      >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
        <span className="text-xs font-medium tracking-wide text-cyan-400">Powered by Claude</span>
      </motion.div>

      {/* Headline */}
      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 mb-5 max-w-4xl text-center font-semibold tracking-tight text-[#f4f5f7]"
        style={{ fontSize: 'clamp(2.5rem, 6.5vw, 5.5rem)', lineHeight: 1.08 }}
      >
        Operate software{' '}
        <span
          className="bg-clip-text text-transparent"
          style={{ backgroundImage: 'linear-gradient(135deg, #22d3ee, #5eead4)' }}
        >
          by talking.
        </span>
      </motion.h1>

      {/* Subheadline */}
      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, delay: 0.18, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 mb-10 max-w-2xl text-center text-base leading-relaxed text-[#9ba3af] sm:text-lg"
      >
        CONXA turns browser workflows into AI-executable operations through Claude. Teach once. Execute forever.
      </motion.p>

      {/* CTAs */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.26, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 mb-16 flex flex-wrap items-center justify-center gap-3"
      >
        <GlowButton href="/sign-up">Start for free</GlowButton>
        <GlowButton href="#pipeline" variant="ghost">See how it works →</GlowButton>
      </motion.div>

      {/* Demo panels */}
      <motion.div
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.9, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 grid w-full max-w-6xl grid-cols-1 gap-4 lg:grid-cols-[1fr_1.6fr]"
        style={{ height: 'clamp(380px, 52vh, 580px)' }}
      >
        <ChatPanel />
        <BrowserSim />
      </motion.div>

      {/* Scroll hint */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.8, duration: 0.8 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2"
      >
        <span className="text-[10px] uppercase tracking-widest text-[#6b7280]">scroll</span>
        <motion.div
          animate={{ y: [0, 6, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
          className="h-4 w-0.5 rounded-full bg-[#6b7280]/40"
        />
      </motion.div>
    </section>
  )
}
