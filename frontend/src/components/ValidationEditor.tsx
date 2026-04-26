import { useLayoutEffect } from 'react'
import { useFieldArray, useFormContext } from 'react-hook-form'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fieldSelectClass } from '@/lib/fieldStyles'
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

function leafTypeOptions(allowNone: boolean) {
  return allowNone ? WAIT_FOR_TYPES : SUBSTANTIVE_WAIT_TYPES
}

export function ValidationEditor() {
  const { register, watch, setValue } = useFormContext()
  const shape = watch('wait_validation_shape')
  const tree = watch('wait_tree') as WaitNode | undefined

  useLayoutEffect(() => {
    if (shape === 'compound' && tree && tree.kind === 'leaf') {
      setValue('wait_tree', { kind: 'group', op: 'or', children: [tree] }, { shouldDirty: true })
    }
    if (shape === 'single' && tree && tree.kind === 'group') {
      setValue('wait_tree', firstLeaf(tree), { shouldDirty: true })
    }
  }, [shape, tree, setValue])

  return (
    <Card>
      <CardHeader className="p-3 pb-2">
        <CardTitle className="text-sm">Validation</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 p-3 pt-0">
        <div className="grid gap-2">
          <Label>Structure</Label>
          <select className={fieldSelectClass} {...register('wait_validation_shape')}>
            <option value="single">Single check</option>
            <option value="compound">Combine checks (nested AND / OR)</option>
          </select>
        </div>
        {shape === 'compound' ? (
          <p className="text-muted-foreground text-xs leading-relaxed">
            Five check types can be mixed in any order. Each branch is one check or a nested subgroup.
          </p>
        ) : null}
        {shape === 'single' ? (
          <LeafBlock basePath="wait_tree" allowNoneOption />
        ) : tree?.kind === 'group' ? (
          <CompoundRootEditor />
        ) : null}
      </CardContent>
    </Card>
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

  return (
    <div className="space-y-3">
      <div className="grid gap-2">
        <Label>Top-level combine as</Label>
        <select className={fieldSelectClass} {...register('wait_tree.op')}>
          <option value="or">Any branch passes (OR)</option>
          <option value="and">Every branch passes (AND)</option>
        </select>
      </div>
      <div className="space-y-2">
        {fields.map((field, index) => (
          <div key={field.id} className="border-border bg-muted/20 rounded-md border p-2">
            <BranchRow
              pathPrefix={`wait_tree.children.${index}`}
              allowLeafNone={false}
              onRemove={() => remove(index)}
            />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
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
          Add check
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
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

  return (
    <div className="border-border bg-background/50 space-y-2 rounded-md border p-2">
      <div className="grid gap-2">
        <Label>Subgroup combine as</Label>
        <select className={fieldSelectClass} {...register(`${pathPrefix}.op` as never)}>
          <option value="or">Any passes (OR)</option>
          <option value="and">All pass (AND)</option>
        </select>
      </div>
      <div className="space-y-2">
        {fields.map((field, index) => (
          <div key={field.id} className="border-border bg-muted/15 rounded border p-2">
            <BranchRow
              pathPrefix={`${pathPrefix}.children.${index}`}
              allowLeafNone={false}
              onRemove={() => remove(index)}
            />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
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
          Add to subgroup
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
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
          Nested subgroup
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
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="grid min-w-0 flex-1 gap-1.5 sm:max-w-xs">
          <span className="text-muted-foreground text-xs">Branch type</span>
          <select
            className={fieldSelectClass}
            value={kind === 'group' ? 'group' : 'leaf'}
            onChange={(e) => setBranchKind(e.target.value === 'group' ? 'group' : 'leaf')}
          >
            <option value="leaf">Single check</option>
            <option value="group">Subgroup (AND/OR)</option>
          </select>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onRemove}>
          Remove
        </Button>
      </div>
      {kind === 'group' ? (
        <GroupAtPath pathPrefix={pathPrefix} />
      ) : (
        <LeafBlock basePath={pathPrefix} allowNoneOption={allowLeafNone} />
      )}
    </div>
  )
}

function LeafBlock({ basePath, allowNoneOption }: { basePath: string; allowNoneOption: boolean }) {
  const { register, watch } = useFormContext()
  const wt = String(watch(`${basePath}.type` as never) ?? '')
  const opts = leafTypeOptions(allowNoneOption)
  return (
    <div className="space-y-3">
      <div className="grid gap-2">
        <Label>Check type</Label>
        <select className={fieldSelectClass} {...register(`${basePath}.type` as never)}>
          {opts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      {(wt === 'element_appear' || wt === 'element_disappear') && (
        <div className="grid gap-2">
          <Label>Selector target</Label>
          <Input type="text" {...register(`${basePath}.target` as never)} placeholder="#element" />
        </div>
      )}
      <div className="grid max-w-xs gap-2">
        <Label>Timeout (ms)</Label>
        <Input
          type="number"
          {...register(`${basePath}.timeout` as never, { valueAsNumber: true })}
        />
      </div>
    </div>
  )
}
