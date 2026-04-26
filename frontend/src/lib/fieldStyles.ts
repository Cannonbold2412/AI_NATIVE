import { cn } from '@/lib/utils'

/** Consistent form controls (matches SkillReviewPage native selects). */
export const fieldSelectClass = cn(
  'border-input bg-background text-foreground flex h-9 w-full min-w-0 rounded-md border px-3 text-sm shadow-xs',
  'focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

export const fieldInputClass = cn(
  'border-input bg-background flex h-9 w-full min-w-0 rounded-md border px-3 text-sm shadow-xs',
  'focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

export const fieldTextareaClass = cn(
  'border-input bg-background min-h-20 w-full rounded-md border px-3 py-2 text-sm shadow-xs',
  'focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none',
  'disabled:cursor-not-allowed disabled:opacity-50',
)
