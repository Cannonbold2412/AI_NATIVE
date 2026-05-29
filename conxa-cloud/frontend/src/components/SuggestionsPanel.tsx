import type { SuggestionItem } from '../types/workflow'
import { useEditorStore } from '../store/editorStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { AlertCircle, Info } from 'lucide-react'

type Props = {
  suggestions: SuggestionItem[]
  open: boolean
  onOpenChange: (open: boolean) => void
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

function SuggestionsList({ suggestions }: { suggestions: SuggestionItem[] }) {
  const setSel = useEditorStore((s) => s.setSelectedStepIndex)

  return (
    <ul className="space-y-2 p-3" role="list">
      {suggestions.length === 0 ? (
        <li className="rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-500">
          No issues for this view.
        </li>
      ) : (
        suggestions.map((s, i) => (
          <li
            key={`${s.step_index}-${s.code}-${i}`}
            className={cn(
              'space-y-1.5 rounded-lg border border-white/8 bg-black/20 p-3',
              s.severity === 'error' && 'border-destructive/30 bg-destructive/5',
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              {severityIcon(s.severity)}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 w-fit min-w-0 flex-1 justify-start gap-1 px-2 font-normal text-zinc-100 hover:bg-white/5 hover:text-white"
                onClick={() => setSel(s.step_index)}
                title="Jump to step"
              >
                <span className="text-xs font-medium">Step {s.step_index + 1}</span>
                <span className="min-w-0 break-all font-mono text-xs">{s.code}</span>
              </Button>
            </div>
            <p className="pl-0.5 text-sm leading-relaxed text-zinc-400">{s.message}</p>
            <div className="pl-0.5">
              <Badge variant="outline" className={cn('text-[0.65rem] font-normal', severityBadgeClass(s.severity))}>
                {s.severity}
              </Badge>
            </div>
          </li>
        ))
      )}
    </ul>
  )
}

export function SuggestionsInlinePanel({ suggestions }: { suggestions: SuggestionItem[] }) {
  return (
    <Card className="border-white/8 bg-white/[0.02] flex min-h-0 flex-1 flex-col shadow-none">
      <CardHeader className="p-3 pb-2">
        <CardTitle className="text-sm text-white">Suggestions</CardTitle>
        <CardDescription className="text-xs text-zinc-500">All steps</CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 p-0">
        <ScrollArea className="min-h-0 h-full">
          <SuggestionsList suggestions={suggestions} />
        </ScrollArea>
      </CardContent>
    </Card>
  )
}

export function SuggestionsPanel({ suggestions, open, onOpenChange }: Props) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[24rem] border-white/10 bg-[#111318] p-0 text-zinc-100 sm:max-w-[24rem]"
      >
        <SheetHeader className="border-b border-white/8 px-4 py-4 text-left">
          <div className="pr-10">
            <SheetTitle className="text-white">Suggestions</SheetTitle>
            <SheetDescription className="text-zinc-500">All steps</SheetDescription>
          </div>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1 p-0">
          <SuggestionsList suggestions={suggestions} />
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}
