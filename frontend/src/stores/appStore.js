import { create } from 'zustand'

const useAppStore = create((set) => ({
  graphData: { nodes: [], links: [] },
  setGraphData: (data) => set({ graphData: data }),
  selectedNodeId: null,
  selectNode: (id) => set({ selectedNodeId: id }),
  relationships: [],
  setRelationships: (rels) => set({ relationships: rels }),
  nodes: [],
  setNodes: (nodes) => set({ nodes }),
  tags: [],
  setTags: (tags) => set({ tags }),
  sidebarFilter: { tag: null, search: '' },
  setFilter: (filter) => set((s) => ({ sidebarFilter: { ...s.sidebarFilter, ...filter } })),
  showEditor: false,
  editingNode: null,
  openEditor: (node) => set({ showEditor: true, editingNode: node }),
  closeEditor: () => set({ showEditor: false, editingNode: null }),
  showImport: false,
  openImport: () => set({ showImport: true }),
  closeImport: () => set({ showImport: false }),
  showAIPanel: false,
  openAIPanel: () => set({ showAIPanel: true }),
  closeAIPanel: () => set({ showAIPanel: false }),
  showChatPanel: false,
  toggleChatPanel: () => set((s) => ({ showChatPanel: !s.showChatPanel })),
  activeConversationId: null,
  setActiveConversationId: (id) => set({ activeConversationId: id }),
}))

export default useAppStore