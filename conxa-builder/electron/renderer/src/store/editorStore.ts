import { create } from "zustand";

interface EditorState {
  selectedStepIndex: number | null;
  dirtySteps: Set<number>;
  validationReport: Record<string, unknown> | null;
  setSelectedStepIndex: (index: number | null) => void;
  markStepDirty: (index: number) => void;
  clearStepDirty: (index: number) => void;
  setValidationReport: (report: Record<string, unknown> | null) => void;
}

export const useEditorStore = create<EditorState>((set) => ({
  selectedStepIndex: null,
  dirtySteps: new Set(),
  validationReport: null,
  setSelectedStepIndex: (index) => set({ selectedStepIndex: index }),
  markStepDirty: (index) =>
    set((s) => {
      const next = new Set(s.dirtySteps);
      next.add(index);
      return { dirtySteps: next };
    }),
  clearStepDirty: (index) =>
    set((s) => {
      const next = new Set(s.dirtySteps);
      next.delete(index);
      return { dirtySteps: next };
    }),
  setValidationReport: (report) => set({ validationReport: report }),
}));
