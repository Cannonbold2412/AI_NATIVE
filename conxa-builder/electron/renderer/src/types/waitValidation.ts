/** Recursive validation.wait_for tree (matches backend JSON: groups use { op, conditions }). */

export type WaitNode =
  | { kind: 'leaf'; type: string; target: string; timeout: number }
  | { kind: 'group'; op: 'and' | 'or'; children: WaitNode[] }
