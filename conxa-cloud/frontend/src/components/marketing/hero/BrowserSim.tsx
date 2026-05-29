'use client'

import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { EXECUTION_SCRIPT, Frame } from './executionScript'
import { Cursor } from './Cursor'

interface SimState {
  cursorX: number
  cursorY: number
  clicking: boolean
  activeTab: string
  url: string
  typingTarget: string
  typingText: string
  checkedItems: string[]
  uploadedFiles: string[]
  toast: { message: string; tone: 'success' | 'info' } | null
  scrollY: number
}

const INIT: SimState = {
  cursorX: 50,
  cursorY: 50,
  clicking: false,
  activeTab: 'HR Portal',
  url: 'hr.acmecorp.internal',
  typingTarget: '',
  typingText: '',
  checkedItems: [],
  uploadedFiles: [],
  toast: null,
  scrollY: 0,
}

const TABS = ['HR Portal', 'Access Control', 'Onboarding Docs']

function sleep(ms: number) {
  return new Promise<void>((res) => setTimeout(res, ms))
}

async function runFrame(frame: Frame, set: (fn: (s: SimState) => SimState) => void): Promise<void> {
  if (frame.kind === 'wait') {
    await sleep(frame.dwell)
    return
  }
  if (frame.kind === 'navigate') {
    set((s) => ({ ...s, activeTab: frame.tab, url: frame.url, typingTarget: '', typingText: '', scrollY: 0 }))
    await sleep(frame.dwell)
    return
  }
  if (frame.kind === 'move') {
    set((s) => ({ ...s, cursorX: frame.to.x, cursorY: frame.to.y }))
    await sleep(frame.duration)
    return
  }
  if (frame.kind === 'click') {
    set((s) => ({ ...s, clicking: true }))
    await sleep(220)
    set((s) => ({ ...s, clicking: false }))
    await sleep(frame.dwell ?? 300)
    return
  }
  if (frame.kind === 'type') {
    set((s) => ({ ...s, typingTarget: frame.target, typingText: '' }))
    for (const ch of frame.text) {
      set((s) => ({ ...s, typingText: s.typingText + ch }))
      await sleep(60 + Math.random() * 40)
    }
    await sleep(frame.dwell ?? 300)
    return
  }
  if (frame.kind === 'check') {
    set((s) => ({ ...s, checkedItems: [...s.checkedItems, frame.target] }))
    await sleep(frame.dwell ?? 400)
    return
  }
  if (frame.kind === 'upload') {
    set((s) => ({ ...s, uploadedFiles: [...s.uploadedFiles, frame.file] }))
    await sleep(frame.dwell ?? 600)
    return
  }
  if (frame.kind === 'toast') {
    set((s) => ({ ...s, toast: { message: frame.message, tone: frame.tone } }))
    await sleep(frame.dwell ?? 1500)
    set((s) => ({ ...s, toast: null }))
    return
  }
  if (frame.kind === 'scroll') {
    set((s) => ({ ...s, scrollY: s.scrollY + frame.amount }))
    await sleep(frame.dwell ?? 400)
    return
  }
}

export function BrowserSim() {
  const [state, setState] = useState<SimState>(INIT)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    let cancelled = false

    async function run() {
      while (!cancelled) {
        setState(INIT)
        await sleep(300)
        for (const frame of EXECUTION_SCRIPT) {
          if (cancelled) return
          await runFrame(frame, (fn) => {
            if (!cancelled) setState(fn)
          })
        }
        await sleep(2000)
        // Fade-reset handled by key prop in parent
      }
    }

    run()
    return () => {
      cancelled = true
      mounted.current = false
    }
  }, [])

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-xl border border-white/8 bg-[#0b0f14] shadow-2xl">
      {/* Browser chrome */}
      <div className="flex h-10 shrink-0 items-center gap-3 border-b border-white/6 bg-[#0f1620] px-4">
        <div className="flex gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-red-500/60" />
          <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/60" />
          <div className="h-2.5 w-2.5 rounded-full bg-green-500/60" />
        </div>
        {/* Address bar */}
        <div className="flex flex-1 items-center gap-2 rounded-md bg-[#06080b] px-3 py-1 text-xs text-[#6b7280]">
          <svg className="h-3 w-3 text-green-400" fill="none" viewBox="0 0 16 16">
            <path d="M8 1a5 5 0 0 1 5 5v1h1a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h1V6a5 5 0 0 1 5-5z" fill="currentColor" fillOpacity={0.5} />
          </svg>
          <span className="truncate">{state.url}</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex shrink-0 items-center gap-0 border-b border-white/6 bg-[#0d1117] px-2">
        {TABS.map((tab) => (
          <div
            key={tab}
            className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs transition-colors ${
              state.activeTab === tab
                ? 'border-cyan-400 text-white'
                : 'border-transparent text-[#6b7280]'
            }`}
          >
            <div className={`h-1.5 w-1.5 rounded-full ${state.activeTab === tab ? 'bg-cyan-400' : 'bg-[#6b7280]'}`} />
            {tab}
          </div>
        ))}
      </div>

      {/* Viewport */}
      <div className="relative flex-1 overflow-hidden">
        <div
          className="absolute inset-0"
          style={{ transform: `translateY(${-state.scrollY}px)`, transition: 'transform 0.5s ease' }}
        >
          <PageContent state={state} />
        </div>

        {/* Cursor */}
        <Cursor x={state.cursorX} y={state.cursorY} clicking={state.clicking} />

        {/* Toast */}
        <AnimatePresence>
          {state.toast && (
            <motion.div
              key="toast"
              initial={{ y: 40, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 40, opacity: 0 }}
              className={`absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm shadow-xl ${
                state.toast.tone === 'success'
                  ? 'border-emerald-500/30 bg-emerald-900/40 text-emerald-300'
                  : 'border-cyan-500/30 bg-cyan-900/40 text-cyan-300'
              }`}
            >
              {state.toast.tone === 'success' ? '✓' : 'ℹ'} {state.toast.message}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function PageContent({ state }: { state: SimState }) {
  if (state.activeTab === 'HR Portal') return <HRPortalPage state={state} />
  if (state.activeTab === 'Access Control') return <AccessControlPage state={state} />
  return <OnboardingDocsPage state={state} />
}

function Field({ label, value, target, state }: { label: string; value?: string; target: string; state: SimState }) {
  const active = state.typingTarget === label
  const text = active ? state.typingText : (value ?? '')
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] text-[#6b7280] uppercase tracking-wider">{label}</label>
      <div
        className={`rounded-md border px-3 py-1.5 text-xs text-white transition-colors ${
          active ? 'border-cyan-400/50 bg-[#06080b]' : 'border-white/8 bg-[#0b0f14]'
        }`}
      >
        {text}
        {active && <span className="ml-0.5 animate-pulse text-cyan-400">|</span>}
      </div>
    </div>
  )
}

function HRPortalPage({ state }: { state: SimState }) {
  return (
    <div className="flex h-full flex-col gap-0">
      {/* Sidebar + main */}
      <div className="flex h-full">
        {/* Sidebar */}
        <div className="w-32 shrink-0 border-r border-white/6 bg-[#0d1117] px-3 py-4">
          <div className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">HR System</div>
          {['Dashboard', 'Employees', 'Payroll', 'Reports', 'Settings'].map((item) => (
            <div
              key={item}
              className={`mb-1 rounded px-2 py-1.5 text-xs ${item === 'Employees' ? 'bg-cyan-500/10 text-cyan-400' : 'text-[#6b7280]'}`}
            >
              {item}
            </div>
          ))}
        </div>
        {/* Main */}
        <div className="flex-1 overflow-auto p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Add Employee</h2>
            <div className="rounded-md bg-cyan-500/10 px-3 py-1 text-xs text-cyan-400 border border-cyan-500/20">+ Add Employee</div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name" target="First name" state={state} />
            <Field label="Last name" target="Last name" state={state} />
            <Field label="Email" target="Email" state={state} />
            <Field label="Department" target="Department" state={state} />
            <Field label="Start date" target="Start date" state={state} />
            <Field label="Manager" target="Manager" value="Sarah Chen" state={state} />
          </div>
          {state.checkedItems.includes('Employee created') && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-900/20 px-3 py-2 text-xs text-emerald-400"
            >
              <span>✓</span> Employee created successfully
            </motion.div>
          )}
        </div>
      </div>
    </div>
  )
}

function AccessControlPage({ state }: { state: SimState }) {
  return (
    <div className="flex h-full">
      <div className="w-32 shrink-0 border-r border-white/6 bg-[#0d1117] px-3 py-4">
        <div className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Access</div>
        {['Overview', 'Role Assignment', 'Audit Log', 'Settings'].map((item) => (
          <div
            key={item}
            className={`mb-1 rounded px-2 py-1.5 text-xs ${item === 'Role Assignment' ? 'bg-cyan-500/10 text-cyan-400' : 'text-[#6b7280]'}`}
          >
            {item}
          </div>
        ))}
      </div>
      <div className="flex-1 p-4">
        <h2 className="mb-3 text-sm font-semibold text-white">Role Assignment</h2>
        <Field label="Search user" target="Search user" state={state} />
        {(state.typingText.length > 0 || state.checkedItems.includes('Permissions applied')) && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-2 rounded-lg border border-white/6 bg-[#0d1117] p-3"
          >
            <div className="flex items-center gap-2 text-xs text-white">
              <div className="h-6 w-6 rounded-full bg-cyan-500/20 text-center text-cyan-400 leading-6">P</div>
              Priya Shah — priya.shah@acmecorp.com
            </div>
          </motion.div>
        )}
        <div className="mt-3 flex flex-col gap-2">
          {['Product Contributor', 'Jira Access', 'Confluence Read'].map((role) => (
            <div key={role} className="flex items-center gap-2 text-xs">
              <div
                className={`flex h-4 w-4 items-center justify-center rounded border ${
                  state.checkedItems.includes('Permissions applied')
                    ? 'border-cyan-400 bg-cyan-400'
                    : 'border-white/20 bg-transparent'
                }`}
              >
                {state.checkedItems.includes('Permissions applied') && (
                  <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                    <path d="M1 3l2 2 4-4" stroke="#06080b" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                )}
              </div>
              <span className="text-[#9ba3af]">{role}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function OnboardingDocsPage({ state }: { state: SimState }) {
  return (
    <div className="flex h-full flex-col p-4 gap-4">
      <h2 className="text-sm font-semibold text-white">Onboarding Documents — Priya Shah</h2>
      <div className="rounded-xl border-2 border-dashed border-white/10 bg-[#0d1117] p-6 text-center">
        <div className="mb-2 text-2xl">📂</div>
        <p className="text-xs text-[#6b7280]">Drop files or click to upload</p>
      </div>
      {state.uploadedFiles.length > 0 && (
        <div className="flex flex-col gap-2">
          {state.uploadedFiles.map((file) => (
            <motion.div
              key={file}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-center gap-2 rounded-lg border border-white/6 bg-[#0d1117] px-3 py-2 text-xs"
            >
              <span className="text-base">📄</span>
              <span className="flex-1 text-[#9ba3af]">{file}</span>
              <span className="text-emerald-400">✓ Uploaded</span>
            </motion.div>
          ))}
        </div>
      )}
      <div className="mt-auto flex justify-end">
        <div className="rounded-md bg-cyan-500/10 px-4 py-2 text-xs text-cyan-400 border border-cyan-500/20">
          Send Welcome Email
        </div>
      </div>
    </div>
  )
}
