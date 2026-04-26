import type { SuggestionItem } from '../types/workflow'
import { useEditorStore } from '../store/editorStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { AlertCircle, Info } from 'lucide-react'

type Props = {
  suggestions: SuggestionItem[]
}

function severityIcon(sev: SuggestionItem['severity']) {
  switch (sev) {
    case 'error':
      return <AlertCircle className="text-destructive size-3.5 shrink-0" aria-hidden />
    case 'warn':
      return <AlertCircle className="text-amber-500 size-3.5 shrink-0" aria-hidden />
    default:
      return <Info className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
  }
}

function severityBadgeClass(sev: SuggestionItem['severity']) {
  switch (sev) {
    case 'error':
      return 'bg-destructive/15 text-destructive border-destructive/30'
    case 'warn':
      return 'bg-amber-500/10 text-amber-200 border-amber-500/30'
    default:
      return 'border-border text-muted-foreground'
  }
}

export function SuggestionsPanel({ suggestions }: Props) {
  const selected = useEditorStore((s) => s.selectedStepIndex)
  const setSel = useEditorStore((s) => s.setSelectedStepIndex)

  const filtered =
    selected === null ? suggestions : suggestions.filter((s) => s.step_index === selected)

  return (
    <aside className="border-border bg-card/20 flex min-h-0 min-w-0 flex-col border-t md:border-t-0 md:border-l">
      <div className="border-border flex flex-col gap-1 border-b p-3">
        <h2 className="text-foreground text-sm font-semibold tracking-tight">Suggestions</h2>
        <p className="text-muted-foreground text-xs">
          {selected === null ? 'All steps' : `Step ${selected + 1}`}
        </p>
        {selected !== null ? (
          <Button type="button" variant="link" size="sm" className="h-auto w-fit px-0" onClick={() => setSel(null)}>
            Show all
          </Button>
        ) : null}
      </div>
      <ScrollArea className="min-h-[8rem] flex-1 p-0">
        <ul className="space-y-2 p-2 pr-3" role="list">
          {filtered.length === 0 ? (
            <li className="text-muted-foreground p-1 text-sm">No issues for this view.</li>
          ) : (
            filtered.map((s, i) => (
              <li
                key={`${s.step_index}-${s.code}-${i}`}
                className={cn(
                  'border-border space-y-1.5 rounded-lg border p-2.5',
                  s.severity === 'error' && 'border-destructive/30 bg-destructive/5',
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  {severityIcon(s.severity)}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-fit min-w-0 flex-1 justify-start gap-1 px-2 font-normal"
                    onClick={() => setSel(s.step_index)}
                    title="Jump to step"
                  >
                    <span className="text-foreground text-xs font-medium">Step {s.step_index + 1}</span>
                    <span className="min-w-0 break-all font-mono text-xs">{s.code}</span>
                  </Button>
                </div>
                <p className="text-muted-foreground pl-0.5 text-sm leading-relaxed">{s.message}</p>
                <div className="pl-0.5">
                  <Badge variant="outline" className={cn('text-[0.65rem] font-normal', severityBadgeClass(s.severity))}>
                    {s.severity}
                  </Badge>
                </div>
              </li>
            ))
          )}
        </ul>
      </ScrollArea>
    </aside>
  )
}
