'use client'

import { useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import { SectionHeader } from '../primitives/SectionHeader'
import { Reveal } from '../primitives/Reveal'

const STAGES = [
  {
    num: '01',
    label: 'Record',
    desc: 'Demonstrate your workflow once in a real browser. CONXA captures every click, type, scroll, and navigation.',
    icon: (
      <svg width="24" height="24" fill="none" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8" stroke="#22d3ee" strokeWidth="1.5" />
        <circle cx="12" cy="12" r="3" fill="#22d3ee" />
      </svg>
    ),
  },
  {
    num: '02',
    label: 'Edit',
    desc: 'Refine the recording in our visual editor. Correct AI interpretation, add conditions, and parameterize inputs.',
    icon: (
      <svg width="24" height="24" fill="none" viewBox="0 0 24 24">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    num: '03',
    label: 'Compile',
    desc: 'CONXA packages your skills into a versioned, executable plugin with deterministic step sequences and recovery layers.',
    icon: (
      <svg width="24" height="24" fill="none" viewBox="0 0 24 24">
        <polyline points="16 18 22 12 16 6" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <polyline points="8 6 2 12 8 18" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    num: '04',
    label: 'Execute',
    desc: 'Claude reads plugin capabilities, plans required skills, and executes at human speed with full observability.',
    icon: (
      <svg width="24" height="24" fill="none" viewBox="0 0 24 24">
        <polygon points="5 3 19 12 5 21 5 3" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
]

export function Pipeline() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: '-15%' })

  return (
    <section id="pipeline" className="relative overflow-hidden bg-[#06080b] px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <SectionHeader
          eyebrow="How it works"
          headline="Teach once. Execute forever."
          sub="Four stages from human demonstration to autonomous AI operation."
        />

        <div ref={ref} className="mt-20 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STAGES.map((stage, i) => (
            <motion.div
              key={stage.label}
              initial={{ opacity: 0, y: 32 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: i * 0.1, ease: [0.16, 1, 0.3, 1] }}
              className="group relative flex flex-col gap-5 rounded-2xl border border-white/6 bg-[#0b0f14] p-6 transition-colors hover:border-cyan-400/20 hover:bg-[#0f1620]"
            >
              {/* Connecting line */}
              {i < STAGES.length - 1 && (
                <div className="absolute right-0 top-1/2 hidden h-px w-4 -translate-y-1/2 translate-x-full bg-gradient-to-r from-white/10 to-transparent lg:block" />
              )}

              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-cyan-400/20 bg-cyan-400/6">
                  {stage.icon}
                </div>
                <span className="font-mono text-3xl font-bold text-white/6 group-hover:text-white/10 transition-colors">
                  {stage.num}
                </span>
              </div>

              <div>
                <h3 className="mb-2 text-base font-semibold text-white">{stage.label}</h3>
                <p className="text-sm leading-relaxed text-[#9ba3af]">{stage.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
