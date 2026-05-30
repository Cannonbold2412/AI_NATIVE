import { create } from 'zustand'

type EditorState = {
  selectedStepIndex: number | null
  dirtySteps: Set<number>
  validationReport: Record<string, unknown> | null
  setSelectedStepIndex: (i: number | null) => void
  markStepDirty: (i: number) => void
  clearStepDirty: (i: number) => void
  clearAllDirty: () => void
  setValidationReport: (r: Record<string, unknown> | null) => void
}

export const useEditorStore = create<EditorState>((set) => ({
  selectedStepIndex: 0,
  dirtySteps: new Set(),
  validationReport: null,
  setSelectedStepIndex: (i) => set({ selectedStepIndex: i }),
  markStepDirty: (i) =>
    set((s) => {
      const n = new Set(s.dirtySteps)
      n.add(i)
      return { dirtySteps: n }
    }),
  clearStepDirty: (i) =>
    set((s) => {
      const n = new Set(s.dirtySteps)
      n.delete(i)
      return { dirtySteps: n }
    }),
  clearAllDirty: () => set({ dirtySteps: new Set() }),
  setValidationReport: (r) => set({ validationReport: r }),
}))
