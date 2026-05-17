'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { SectionHeader } from '../primitives/SectionHeader'
import { Reveal } from '../primitives/Reveal'

const LAYERS = [
  {
    num: 'Layer 1',
    label: 'Selector Recovery',
    desc: 'Tries alternative CSS selectors, text content matches, and aria-label variants before escalating. Handles 80% of UI drift automatically.',
    color: '#22d3ee',
  },
  {
    num: 'Layer 2',
    label: 'Anchor Targeting',
    desc: 'Uses surrounding page structure as positional anchors — "button to the right of the first table row" — immune to attribute changes.',
    color: '#5eead4',
  },
  {
    num: 'Layer 3',
    label: 'LLM Intent Recovery',
    desc: 'Claude analyzes the current page DOM and infers the correct element based on semantic intent of the original step.',
    color: '#a78bfa',
  },
  {
    num: 'Layer 4',
    label: 'Vision Recovery',
    desc: 'Screenshots the viewport and uses multimodal AI to identify the target element visually — handles complete layout overhauls.',
    color: '#f0abfc',
  },
  {
    num: 'Layer 0',
    label: 'Terminal Failure',
    desc: 'All recovery layers exhausted. The workflow halts, logs the exact failure state with full context, and notifies the operator for re-teaching.',
    color: '#f87171',
  },
]

export function RecoveryLayers() {
  const [active, setActive] = useState<number | null>(null)

  return (
    <section id="recovery" className="relative bg-[#06080b] px-6 py-28">
      {/* Subtle radial glow */}
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-[0.04]"
        style={{ background: 'radial-gradient(circle, #22d3ee, transparent 70%)', filter: 'blur(60px)' }}
      />

      <div className="relative mx-auto max-w-5xl">
        <SectionHeader
          eyebrow="Self-healing execution"
          headline="Five layers between failure and recovery."
          sub="When a UI changes, CONXA doesn't crash — it tries every recovery strategy in sequence before asking for help."
        />

        <div className="mt-16 flex flex-col gap-3">
          {LAYERS.map((layer, i) => (
            <Reveal key={layer.label} delay={i * 0.07}>
              <motion.button
                className="w-full rounded-2xl border border-white/6 bg-[#0b0f14] p-5 text-left transition-colors hover:border-white/10"
                onClick={() => setActive(active === i ? null : i)}
                style={{
                  borderColor: active === i ? `${layer.color}30` : undefined,
                  background: active === i ? `${layer.color}06` : undefined,
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-xs font-mono font-semibold"
                      style={{ color: layer.color, background: `${layer.color}12`, border: `1px solid ${layer.color}22` }}
                    >
                      {i === 4 ? '0' : i + 1}
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-widest" style={{ color: layer.color }}>
                        {layer.num}
                      </span>
                      <h3 className="text-sm font-semibold text-white">{layer.label}</h3>
                    </div>
                  </div>
                  <motion.div
                    animate={{ rotate: active === i ? 45 : 0 }}
                    transition={{ duration: 0.2 }}
                    className="flex h-5 w-5 items-center justify-center text-[#6b7280]"
                  >
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                  </motion.div>
                </div>

                <AnimatePresence>
                  {active === i && (
                    <motion.p
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                      className="mt-4 overflow-hidden pl-12 text-sm leading-relaxed text-[#9ba3af]"
                    >
                      {layer.desc}
                    </motion.p>
                  )}
                </AnimatePresence>
              </motion.button>
            </Reveal>
          ))}
        </div>

        {/* Flow indicator */}
        <Reveal delay={0.4}>
          <div className="mt-8 flex items-center justify-center gap-3 text-xs text-[#6b7280]">
            {LAYERS.slice(0, 4).map((l, i) => (
              <span key={l.num} className="flex items-center gap-2">
                <span style={{ color: l.color }}>{l.num}</span>
                {i < 3 && <span className="text-[#3f4751]">→</span>}
              </span>
            ))}
            <span className="text-[#3f4751]">→</span>
            <span style={{ color: '#f87171' }}>Terminal</span>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
