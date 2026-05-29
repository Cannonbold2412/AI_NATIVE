import { type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type PageHeaderProps = {
  title: string
  description?: ReactNode
  actions?: ReactNode
  className?: string
}

export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <div className={cn('border-b border-white/8 px-4 py-4 sm:px-6', className)}>
      <div className="flex min-h-10 items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className={cn('truncate text-base font-semibold text-white sm:text-lg', description && 'leading-snug')}>
            {title}
          </h1>
          {description != null && description !== false ? (
            <div className={cn('mt-0.5 min-w-0', typeof description === 'string' ? 'truncate text-sm text-zinc-500' : 'text-sm text-zinc-500')}>
              {description}
            </div>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  )
}
