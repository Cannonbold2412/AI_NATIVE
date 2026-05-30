'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CHAT_STEPS } from './executionScript'

interface VisibleStep {
  role: 'user' | 'assistant' | 'tool'
  text: string
  icon?: string
  completed?: boolean
}

function useTypewriter(text: string, speed = 28) {
  const [displayed, setDisplayed] = useState('')
  useEffect(() => {
    setDisplayed('')
    let i = 0
    const id = setInterval(() => {
      if (i >= text.length) { clearInterval(id); return }
      setDisplayed(text.slice(0, i + 1))
      i++
    }, speed)
    return () => clearInterval(id)
  }, [text, speed])
  return displayed
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-1 py-0.5">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-[#9ba3af]"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1, delay: i * 0.2, repeat: Infinity }}
        />
      ))}
    </div>
  )
}

export function ChatPanel() {
  const [steps, setSteps] = useState<VisibleStep[]>([])
  const [typing, setTyping] = useState(false)
  const [completedTools, setCompletedTools] = useState<Set<number>>(() => new Set())

  useEffect(() => {
    let cancelled = false
    const timers: ReturnType<typeof setTimeout>[] = []

    function reset() {
      setSteps([])
      setTyping(false)
      setCompletedTools(new Set())
    }

    reset()

    // Type user message with typewriter simulation
    timers.push(setTimeout(() => {
      if (cancelled) return
      setSteps([{ role: 'user', text: CHAT_STEPS[0].text }])
      setTyping(true)
    }, 600))

    timers.push(setTimeout(() => {
      if (cancelled) return
      setTyping(false)
    }, 1400))

    CHAT_STEPS.slice(1).forEach((step, idx) => {
      timers.push(setTimeout(() => {
        if (cancelled) return
        setSteps((s) => [...s, { role: step.role, text: step.text, icon: 'icon' in step ? (step as { icon?: string }).icon : undefined }])
        if (step.role === 'tool') {
          const toolIdx = idx
          setTimeout(() => {
            if (!cancelled) setCompletedTools((s) => new Set([...s, toolIdx]))
          }, 2200)
        }
      }, step.delay))
    })

    // Full loop: restart after ~32s
    timers.push(setTimeout(() => {
      if (cancelled) return
      reset()
    }, 32000))

    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
    }
  }, [])

  return (
    <div className="flex h-full flex-col rounded-xl border border-white/8 bg-[#0b0f14] shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="flex h-10 shrink-0 items-center gap-3 border-b border-white/6 bg-[#0f1620] px-4">
        <div className="flex h-5 w-5 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-teal-300">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <circle cx="5" cy="5" r="3" fill="#06080b" />
          </svg>
        </div>
        <span className="text-xs font-medium text-white">Claude — CONXA Runtime</span>
        <div className="ml-auto flex items-center gap-1.5">
          <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          <span className="text-[10px] text-[#6b7280]">executing</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex flex-1 flex-col gap-3 overflow-auto p-4 scrollbar-hide">
        <AnimatePresence initial={false}>
          {steps.map((step, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            >
              {step.role === 'user' && (
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-[#1a2332] px-4 py-2.5 text-sm text-white">
                    {step.text}
                  </div>
                </div>
              )}
              {step.role === 'assistant' && (
                <div className="flex gap-2.5">
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-teal-300">
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <circle cx="5" cy="5" r="3" fill="#06080b" />
                    </svg>
                  </div>
                  <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-[#0f1620] px-4 py-2.5 text-sm text-[#e5e7eb]">
                    <AssistantText text={step.text} index={i} />
                  </div>
                </div>
              )}
              {step.role === 'tool' && (
                <div className="flex gap-2.5">
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-teal-300">
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <circle cx="5" cy="5" r="3" fill="#06080b" />
                    </svg>
                  </div>
                  <div
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-mono transition-colors ${
                      completedTools.has(i - 1)
                        ? 'border-emerald-500/20 bg-emerald-900/10 text-emerald-400'
                        : 'border-cyan-500/20 bg-cyan-900/10 text-cyan-400'
                    }`}
                  >
                    <span>
                      {completedTools.has(i - 1) ? '✓' : '⟳'}
                    </span>
                    <span>{step.icon} {step.text}</span>
                  </div>
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {typing && (
          <div className="flex gap-2.5">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-teal-300">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <circle cx="5" cy="5" r="3" fill="#06080b" />
              </svg>
            </div>
            <div className="rounded-2xl rounded-tl-sm bg-[#0f1620] px-4 py-2.5">
              <TypingDots />
            </div>
          </div>
        )}
      </div>

      {/* Input (decorative) */}
      <div className="shrink-0 border-t border-white/6 p-3">
        <div className="flex items-center gap-2 rounded-lg border border-white/8 bg-[#0f1620] px-3 py-2">
          <span className="flex-1 text-xs text-[#6b7280]">Ask CONXA to operate…</span>
          <div className="flex h-5 w-5 items-center justify-center rounded bg-cyan-500/20">
            <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
              <path d="M1 4h6M4 1l3 3-3 3" stroke="#22d3ee" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  )
}

function AssistantText({ text, index }: { text: string; index: number }) {
  const displayed = useTypewriter(index > 0 ? text : '')
  return <>{displayed || text}</>
}
