// apps/web/src/features/files/components/file-selection.ts

export type FileSelectionState = {
  moveFileIds: string[]
  scope: string
  selectedIds: Set<string>
}

export type FileSelectionAction =
  | { type: "move-close" }
  | { fileIds: string[]; type: "move-open" }
  | { type: "move-success" }
  | { scope: string; type: "scope-change" }
  | { fileId: string; selected: boolean; type: "selection-change" }

export function initialFileSelectionState(scope: string): FileSelectionState {
  return { moveFileIds: [], scope, selectedIds: new Set() }
}

export function fileSelectionReducer(
  state: FileSelectionState,
  action: FileSelectionAction
): FileSelectionState {
  switch (action.type) {
    case "move-close":
      return { ...state, moveFileIds: [] }
    case "move-open":
      return { ...state, moveFileIds: action.fileIds }
    case "move-success":
      return { ...state, moveFileIds: [], selectedIds: new Set() }
    case "scope-change":
      return action.scope === state.scope ? state : initialFileSelectionState(action.scope)
    case "selection-change": {
      const selectedIds = new Set(state.selectedIds)
      if (action.selected) selectedIds.add(action.fileId)
      else selectedIds.delete(action.fileId)
      return { ...state, selectedIds }
    }
  }
}
