'use client'

import dynamic from 'next/dynamic'
import { useRef, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { SectionHeader } from '../primitives/SectionHeader'
import { Reveal } from '../primitives/Reveal'

const OrchestrationScene = dynamic(
  () => import('../3d/OrchestrationScene').then((m) => m.OrchestrationScene),
  { ssr: false, loading: () => <div className="h-full w-full" /> },
)

const LOG_LINES = [
  { time: '09:14:02', plugin: 'hr-onboarding', skill: 'create-employee', status: 'ok', layer: null },
  { time: '09:14:05', plugin: 'hr-onboarding', skill: 'assign-permissions', status: 'ok', layer: null },
  { time: '09:14:09', plugin: 'hr-onboarding', skill: 'upload-documents', status: 'ok', layer: null },
  { time: '09:14:12', plugin: 'access-control', skill: 'role-assignment', status: 'recovered', layer: 'L2' },
  { time: '09:14:16', plugin: 'payroll-sync', skill: 'sync-employee', status: 'ok', layer: null },
  { time: '09:14:21', plugin: 'email-admin', skill: 'send-welcome', status: 'ok', layer: null },
  { time: '09:14:24', plugin: 'finance-ops', skill: 'create-cost-center', status: 'recovered', layer: 'L1' },
  { time: '09:14:28', plugin: 'hr-onboarding', skill: 'complete-checklist', status: 'ok', layer: null },
]

export function ObservableRuntime() {
  const [visibleCount, setVisibleCount] = useState(3)

  useEffect(() => {
    const id = setInterval(() => {
      setVisibleCount((v) => (v >= LOG_LINES.length ? 3 : v + 1))
    }, 1800)
    return () => clearInterval(id)
  }, [])

  return (
    <section id="observability" className="relative bg-[#0b0f14] px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <SectionHeader
          eyebrow="Observable runtime"
          headline="Every execution, fully visible."
          sub="Watch your AI operator work in real time. Streamed logs, recovery events, and execution timelines — nothing is a black box."
        />

        <div className="mt-16 grid gap-6 lg:grid-cols-[1fr_1.2fr]">
          {/* 3D scene */}
          <Reveal direction="left">
            <div className="relative h-80 overflow-hidden rounded-2xl border border-white/6 bg-[#06080b] lg:h-[440px]">
              <OrchestrationScene />
              <div className="absolute inset-0 flex flex-col items-center justify-end gap-2 p-4">
                <p className="text-[10px] uppercase tracking-widest text-[#6b7280]">Operational node graph</p>
              </div>
            </div>
          </Reveal>

          {/* Streaming log */}
          <Reveal direction="right">
            <div className="flex flex-col rounded-2xl border border-white/6 bg-[#06080b] overflow-hidden">
              <div className="flex h-9 items-center gap-3 border-b border-white/6 bg-[#0b0f14] px-4">
                <div className="flex gap-1.5">
                  <div className="h-2 w-2 rounded-full bg-white/10" />
                  <div className="h-2 w-2 rounded-full bg-white/10" />
                  <div className="h-2 w-2 rounded-full bg-white/10" />
                </div>
                <span className="text-[10px] text-[#6b7280]">execution log — live</span>
                <div className="ml-auto flex items-center gap-1.5">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                  <span className="text-[10px] text-emerald-400">streaming</span>
                </div>
              </div>
              <div className="flex flex-col gap-0 p-2 font-mono text-xs overflow-auto" style={{ minHeight: 360 }}>
                {LOG_LINES.slice(0, visibleCount).map((line, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.3 }}
                    className="flex items-center gap-3 rounded px-2 py-1.5 hover:bg-white/3"
                  >
                    <span className="w-16 shrink-0 text-[#6b7280]">{line.time}</span>
                    <span className="text-cyan-400/80">{line.plugin}</span>
                    <span className="text-[#6b7280]">›</span>
                    <span className="flex-1 text-[#9ba3af]">{line.skill}</span>
                    {line.layer && (
                      <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
                        {line.layer}
                      </span>
                    )}
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${
                        line.status === 'ok'
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : 'bg-amber-500/10 text-amber-400'
                      }`}
                    >
                      {line.status}
                    </span>
                  </motion.div>
                ))}
                <div className="flex items-center gap-1 px-2 py-1.5">
                  <motion.span
                    animate={{ opacity: [1, 0, 1] }}
                    transition={{ duration: 1, repeat: Infinity }}
                    className="text-cyan-400"
                  >
                    ▌
                  </motion.span>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  )
}
