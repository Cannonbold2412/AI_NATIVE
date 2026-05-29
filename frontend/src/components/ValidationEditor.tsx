import { type ReactNode, useId, useLayoutEffect } from 'react'
import { useFieldArray, useFormContext } from 'react-hook-form'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fieldSelectClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'
import type { WaitNode } from '../types/waitValidation'

/** Five substantive wait kinds (plus none for “no wait” in single mode). */
export const SUBSTANTIVE_WAIT_TYPES = [
  { value: 'url_change', label: 'URL change' },
  { value: 'element_appear', label: 'Element appear' },
  { value: 'element_disappear', label: 'Element disappear' },
  { value: 'intent_outcome', label: 'Intent / text outcome' },
  { value: 'dom_change', label: 'DOM change' },
] as const

export const WAIT_FOR_TYPES = [{ value: 'none', label: 'None' }, ...SUBSTANTIVE_WAIT_TYPES] as const

const CHECK_TYPE_HELP: Record<string, string> = {
  none: 'No wait — proceed after the action.',
  url_change: 'Waits for navigation or URL to change.',
  element_appear: 'Waits until a selector matches a visible node.',
  element_disappear: 'Waits until a selector no longer matches.',
  intent_outcome: 'Waits for text that matches the step intent.',
  dom_change: 'Waits for a substantial DOM or layout change.',
  dom: 'Waits for a substantial DOM or layout change.',
}

function leafTypeOptions(allowNone: boolean) {
  return allowNone ? WAIT_FOR_TYPES : SUBSTANTIVE_WAIT_TYPES
}

export function ValidationEditor() {
  const { register, watch, setValue } = useFormContext()
  const shape = watch('wait_validation_shape') as 'single' | 'compound' | undefined
  const tree = watch('wait_tree') as WaitNode | undefined
  const structId = useId()

  useLayoutEffect(() => {
    if (shape === 'compound' && tree && tree.kind === 'leaf') {
      setValue('wait_tree', { kind: 'group', op: 'or', children: [tree] }, { shouldDirty: true })
    }
    if (shape === 'single' && tree && tree.kind === 'group') {
      setValue('wait_tree', firstLeaf(tree), { shouldDirty: true })
    }
  }, [shape, tree, setValue])

  return (
    <Card size="sm" className="border-border/50 shadow-none ring-0">
      <CardHeader className="px-3 pb-2 pt-3 sm:px-4">
        <CardTitle className="text-sm font-medium">Validation</CardTitle>
        <p className="text-muted-foreground mt-0.5 text-xs leading-snug">
          Conditions that must be satisfied (or time out) before this step is considered done.
        </p>
      </CardHeader>
      <CardContent className="space-y-4 px-3 pb-3 sm:px-4">
        <div className="space-y-2">
          <span className="text-muted-foreground text-xs font-medium" id={`${structId}-mode-label`}>
            Mode
          </span>
          <div
            className="bg-muted/40 border-border/60 flex max-w-md rounded-md border p-0.5"
            role="group"
            aria-labelledby={`${structId}-mode-label`}
          >
            <ModeButton active={shape === 'single'} onClick={() => setValue('wait_validation_shape', 'single', { shouldDirty: true })}>
              Single
            </ModeButton>
            <ModeButton
              active={shape === 'compound'}
              onClick={() => setValue('wait_validation_shape', 'compound', { shouldDirty: true })}
            >
              Compound
            </ModeButton>
          </div>
          {/* Keep native select in DOM for a11y / tests that hook name; visually hidden, synced with segmented control */}
          <label htmlFor={structId} className="sr-only">
            Wait validation structure
          </label>
          <select id={structId} className="sr-only" aria-hidden tabIndex={-1} {...register('wait_validation_shape')}>
            <option value="single">Single check</option>
            <option value="compound">Combine checks (nested AND / OR)</option>
          </select>
        </div>

        {shape === 'single' ? (
          <LeafBlock basePath="wait_tree" allowNoneOption variant="root" />
        ) : tree?.kind === 'group' ? (
          <CompoundRootEditor />
        ) : null}
      </CardContent>
    </Card>
  )
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'min-h-8 flex-1 rounded-[4px] px-2.5 py-1.5 text-sm font-medium transition-colors',
        active
          ? 'bg-background text-foreground border-border/50 shadow-sm border'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function firstLeaf(n: WaitNode): WaitNode {
  if (n.kind === 'leaf') return n
  for (const c of n.children) {
    const f = firstLeaf(c)
    if (f.kind === 'leaf') return f
  }
  return { kind: 'leaf', type: 'none', target: '', timeout: 5000 }
}

function CompoundRootEditor() {
  const { register, control } = useFormContext()
  const { fields, append, remove } = useFieldArray({ control, name: 'wait_tree.children' as never })
  const combineId = useId()

  return (
    <div className="space-y-3">
      <div className="grid max-w-md gap-1.5">
        <Label className="text-foreground" htmlFor={combineId}>
          Combine as
        </Label>
        <select className={fieldSelectClass} id={combineId} {...register('wait_tree.op')}>
          <option value="or">OR — any branch</option>
          <option value="and">AND — all branches</option>
        </select>
      </div>

      {fields.length === 0 ? (
        <p className="text-muted-foreground border-border/60 rounded-md border border-dashed py-4 text-center text-xs">
          No branches yet
        </p>
      ) : (
        <ul className="space-y-2">
          {fields.map((field, index) => (
            <li
              key={field.id}
              className="border-border/50 bg-muted/15 rounded-md border p-2.5"
            >
              <span className="text-muted-foreground mb-2 block text-[10px] font-semibold uppercase tracking-wider">
                Branch {index + 1}
              </span>
              <BranchRow
                pathPrefix={`wait_tree.children.${index}`}
                allowLeafNone={false}
                onRemove={() => remove(index)}
              />
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() =>
            append({
              kind: 'leaf',
              type: 'url_change',
              target: '',
              timeout: 5000,
            } as WaitNode)
          }
        >
          Add branch
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() =>
            append({
              kind: 'group',
              op: 'or',
              children: [
                { kind: 'leaf', type: 'element_appear', target: '', timeout: 5000 },
                { kind: 'leaf', type: 'url_change', target: '', timeout: 5000 },
              ],
            } as WaitNode)
          }
        >
          Add subgroup
        </Button>
      </div>
    </div>
  )
}

function GroupAtPath({ pathPrefix }: { pathPrefix: string }) {
  const { register, control } = useFormContext()
  const { fields, append, remove } = useFieldArray({
    control,
    name: `${pathPrefix}.children` as never,
  })
  const subId = useId()

  return (
    <div className="border-border/50 bg-background/30 space-y-2.5 rounded-md border p-2.5">
      <div className="grid max-w-sm gap-1.5">
        <Label className="text-foreground" htmlFor={subId}>
          Subgroup
        </Label>
        <select className={fieldSelectClass} id={subId} {...register(`${pathPrefix}.op` as never)}>
          <option value="or">OR — any</option>
          <option value="and">AND — all</option>
        </select>
      </div>
      <ul className="space-y-1.5">
        {fields.map((field, index) => (
          <li key={field.id} className="bg-muted/10 rounded border border-border/40 p-2">
            <BranchRow
              pathPrefix={`${pathPrefix}.children.${index}`}
              allowLeafNone={false}
              onRemove={() => remove(index)}
            />
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() =>
            append({
              kind: 'leaf',
              type: 'url_change',
              target: '',
              timeout: 5000,
            } as WaitNode)
          }
        >
          Add
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() =>
            append({
              kind: 'group',
              op: 'and',
              children: [
                { kind: 'leaf', type: 'dom_change', target: '', timeout: 5000 },
                { kind: 'leaf', type: 'intent_outcome', target: '', timeout: 5000 },
              ],
            } as WaitNode)
          }
        >
          Nested
        </Button>
      </div>
    </div>
  )
}

function BranchRow({
  pathPrefix,
  allowLeafNone,
  onRemove,
}: {
  pathPrefix: string
  allowLeafNone: boolean
  onRemove: () => void
}) {
  const { watch, getValues, setValue } = useFormContext()
  const kind = watch(`${pathPrefix}.kind` as never) as unknown as 'leaf' | 'group' | undefined
  const brId = useId()
  const isLeaf = kind !== 'group'

  const setBranchKind = (next: 'leaf' | 'group') => {
    const cur = getValues(pathPrefix) as WaitNode
    if (!cur) return
    if (next === 'group' && cur.kind === 'leaf') {
      setValue(
        pathPrefix,
        {
          kind: 'group',
          op: 'or',
          children: [cur, { kind: 'leaf', type: 'url_change', target: '', timeout: 5000 }],
        } as WaitNode,
        { shouldDirty: true },
      )
    } else if (next === 'leaf' && cur.kind === 'group') {
      setValue(pathPrefix, firstLeaf(cur), { shouldDirty: true })
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-1.5">
        <div className="grid min-w-0 gap-1 sm:w-[8.5rem]">
          <Label className="text-foreground" htmlFor={brId}>
            Type
          </Label>
          <select
            id={brId}
            className={cn(fieldSelectClass, 'h-8 px-2 text-xs')}
            value={kind === 'group' ? 'group' : 'leaf'}
            onChange={(e) => setBranchKind(e.target.value === 'group' ? 'group' : 'leaf')}
            aria-label="Branch type"
          >
            <option value="leaf">Check</option>
            <option value="group">Subgroup</option>
          </select>
        </div>
        {isLeaf ? <LeafInlineFields basePath={pathPrefix} allowNoneOption={allowLeafNone} /> : null}
        <Button type="button" size="sm" variant="ghost" className="text-muted-foreground h-7 shrink-0 px-2" onClick={onRemove}>
          Remove
        </Button>
      </div>
      {kind === 'group' ? (
        <GroupAtPath pathPrefix={pathPrefix} />
      ) : (
        <LeafTargetField basePath={pathPrefix} />
      )}
    </div>
  )
}

function LeafInlineFields({ basePath, allowNoneOption }: { basePath: string; allowNoneOption: boolean }) {
  const { register, watch } = useFormContext()
  const wt = String(watch(`${basePath}.type` as never) ?? '')
  const opts = leafTypeOptions(allowNoneOption)
  const id = useId()
  const typeId = `${id}-type`
  const timeoutId = `${id}-timeout`
  const regType = register(`${basePath}.type` as never)
  const regTimeout = register(`${basePath}.timeout` as never, { valueAsNumber: true })
  const helpLine = CHECK_TYPE_HELP[wt] ?? 'Until satisfied or timeout.'

  return (
    <>
      <div className="grid min-w-0 flex-1 gap-1 sm:min-w-[10.5rem]">
        <Label className="text-foreground" htmlFor={typeId}>
          Check
        </Label>
        <select
          className={cn(fieldSelectClass, 'h-8 px-2 text-xs')}
          id={typeId}
          title={helpLine}
          {...regType}
          aria-label="Wait check type"
        >
          {opts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="grid min-w-0 gap-1 sm:mr-1 sm:w-[7.5rem]">
        <Label className="text-foreground" htmlFor={timeoutId}>
          Timeout (ms)
        </Label>
        <Input
          type="number"
          id={timeoutId}
          min={0}
          step={100}
          className="h-8 tabular-nums px-2 text-xs"
          placeholder="5000"
          {...regTimeout}
        />
      </div>
    </>
  )
}

function LeafTargetField({ basePath }: { basePath: string }) {
  const { register, watch } = useFormContext()
  const wt = String(watch(`${basePath}.type` as never) ?? '')
  const id = useId()
  const targetId = `${id}-target`
  const regTarget = register(`${basePath}.target` as never)

  if (wt !== 'element_appear' && wt !== 'element_disappear') return null

  return (
    <div className="space-y-1.5">
      <Label className="text-foreground" htmlFor={targetId}>
        Selector
      </Label>
      <Input
        type="text"
        id={targetId}
        {...regTarget}
        placeholder="CSS selector"
        autoComplete="off"
      />
    </div>
  )
}

function LeafBlock({
  basePath,
  allowNoneOption,
  variant = 'root',
}: {
  basePath: string
  allowNoneOption: boolean
  variant?: 'root' | 'nested'
}) {
  const { register, watch } = useFormContext()
  const wt = String(watch(`${basePath}.type` as never) ?? '')
  const opts = leafTypeOptions(allowNoneOption)
  const id = useId()
  const typeId = `${id}-type`
  const targetId = `${id}-target`
  const timeoutId = `${id}-timeout`
  const regType = register(`${basePath}.type` as never)
  const regTarget = register(`${basePath}.target` as never)
  const regTimeout = register(`${basePath}.timeout` as never, { valueAsNumber: true })
  const helpLine = CHECK_TYPE_HELP[wt] ?? 'Until satisfied or timeout.'

  const fields = (
    <div
      className={cn(
        'space-y-3',
        variant === 'root' && 'pt-0.5',
        variant === 'nested' && 'pt-0',
      )}
    >
      <div className="grid gap-3 sm:grid-cols-2 sm:items-start sm:gap-4">
        <div className="min-w-0 space-y-1.5 sm:col-span-1">
          <Label className="text-foreground" htmlFor={typeId}>
            {variant === 'root' ? 'Condition' : 'Check'}
          </Label>
          <select
            className={fieldSelectClass}
            id={typeId}
            title={helpLine}
            {...regType}
            aria-label="Wait check type"
          >
            {opts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5 sm:col-span-1 sm:pt-0">
          <Label className="text-foreground" htmlFor={timeoutId}>
            Timeout (ms)
          </Label>
          <Input
            type="number"
            id={timeoutId}
            min={0}
            step={100}
            className="tabular-nums"
            placeholder="5000"
            {...regTimeout}
          />
        </div>
      </div>
      {(wt === 'element_appear' || wt === 'element_disappear') && (
        <div className="space-y-1.5">
          <Label className="text-foreground" htmlFor={targetId}>
            Selector
          </Label>
          <Input
            type="text"
            id={targetId}
            {...regTarget}
            placeholder="CSS selector"
            autoComplete="off"
          />
        </div>
      )}
    </div>
  )

  if (variant === 'root') {
    return <div className="border-border/40 space-y-2 border-t pt-3">{fields}</div>
  }
  return fields
}
