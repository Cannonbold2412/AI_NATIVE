import { type ReactNode } from 'react'
import { CheckCircle2, Circle, AlertCircle, Lock } from 'lucide-react'
import { cn } from '@/lib/utils'

export type StepState = 'done' | 'active' | 'blocked' | 'pending'

export type PipelineStep = {
  label: string
  state: StepState
  subtitle?: string
}

const stateConfig: Record<StepState, {
  icon: ReactNode
  node: string
  label: string
  connector: string
}> = {
  done: {
    icon: <CheckCircle2 className="size-4" />,
    node: 'border-emerald-500/60 bg-emerald-500/15 text-emerald-400',
    label: 'text-emerald-300',
    connector: 'bg-emerald-500/30',
  },
  active: {
    icon: <Circle className="size-4 fill-sky-400 text-sky-400" />,
    node: 'border-sky-500/60 bg-sky-500/15 text-sky-400',
    label: 'text-white font-semibold',
    connector: 'bg-white/10',
  },
  blocked: {
    icon: <AlertCircle className="size-4" />,
    node: 'border-amber-500/50 bg-amber-500/10 text-amber-400',
    label: 'text-amber-300',
    connector: 'bg-white/8',
  },
  pending: {
    icon: <Lock className="size-4" />,
    node: 'border-white/10 bg-white/[0.03] text-zinc-600',
    label: 'text-zinc-600',
    connector: 'bg-white/8',
  },
}

export function BuildPipelineStepper({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="flex items-start gap-0">
      {steps.map((step, i) => {
        const cfg = stateConfig[step.state]
        const isLast = i === steps.length - 1
        return (
          <div key={step.label} className="flex flex-1 items-start">
            {/* Step node */}
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full border',
                  cfg.node,
                )}
              >
                {cfg.icon}
              </div>
              <p className={cn('mt-1.5 text-center text-[11px] leading-tight whitespace-nowrap', cfg.label)}>
                {step.label}
              </p>
              {step.subtitle && (
                <p className="mt-0.5 text-center text-[10px] text-zinc-600 leading-tight">
                  {step.subtitle}
                </p>
              )}
            </div>
            {/* Connector line */}
            {!isLast && (
              <div className={cn('mt-4 h-px flex-1', cfg.connector)} />
            )}
          </div>
        )
      })}
    </div>
  )
}
