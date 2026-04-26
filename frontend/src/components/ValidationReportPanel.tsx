import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

type Props = {
  data: Record<string, unknown> | null
  title?: ReactNode
  defaultOpen?: boolean
}

/**
 * Collapsible JSON readout (validation / audit) — same pattern 21st.dev / inspector tools target.
 */
export function ValidationReportPanel({ data, title = 'Validation report', defaultOpen = true }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  if (!data) return null
  return (
    <div className="bg-muted/20 border-border w-full border-b">
      <Collapsible open={open} onOpenChange={setOpen} className="w-full">
        <CollapsibleTrigger
          className="hover:bg-muted/40 text-muted-foreground focus-visible:ring-ring/50 flex w-full items-center justify-between gap-2 border-0 bg-transparent px-3 py-2 text-left text-xs font-medium tracking-wide uppercase focus-visible:ring-2 focus-visible:outline-none"
          aria-expanded={open}
        >
          <span>{title}</span>
          <ChevronDown
            className={cn('text-muted-foreground size-4 shrink-0 transition-transform duration-200', open && 'rotate-180')}
            aria-hidden
          />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ScrollArea className="h-40 border-t" role="region" aria-label="Validation result JSON" tabIndex={0}>
            <pre className="text-muted-foreground p-3 font-mono text-xs break-words whitespace-pre-wrap">
              {JSON.stringify(data, null, 2)}
            </pre>
          </ScrollArea>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
