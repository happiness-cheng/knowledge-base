const API_BASE = '/api'

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache', ...options.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API error: ${res.status} ${await res.text()}`)
  return res.json()
}

export const api = {
  getNodes: (params = {}) => {
    const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v)))
    // Bust cache when no specific params
    if (!Object.keys(params).length) qs.set('_t', Date.now())
    return apiFetch(`/nodes?${qs}`)
  },
  getNode: (id) => apiFetch(`/nodes/${id}`),
  createNode: (data) => apiFetch('/nodes', { method: 'POST', body: JSON.stringify(data) }),
  updateNode: (id, data) => apiFetch(`/nodes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteNode: (id) => apiFetch(`/nodes/${id}`, { method: 'DELETE' }),
  getNodeSubtopics: (id) => apiFetch(`/nodes/${id}/subtopics`),
  getSuggestedLinks: (id) => apiFetch(`/nodes/${id}/suggested-links`),

  getGraph: () => apiFetch('/graph'),
  getSubgraph: (nodeId, hops = 1) => apiFetch(`/graph/node/${nodeId}?hops=${hops}`),

  importFile: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/import/file`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(`Import failed: ${res.status} ${await res.text()}`)
    return res.json()
  },
  importBatch: async (files) => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    const res = await fetch(`${API_BASE}/import/batch`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(`Batch import failed: ${res.status} ${await res.text()}`)
    return res.json()
  },
  importText: (text, title) => apiFetch('/import/text', {
    method: 'POST', body: JSON.stringify({ content: text, title }),
  }),

  analyzeNode: (id) => apiFetch(`/ai/analyze-node/${id}`, { method: 'POST' }),
  findRelationships: (nodeIds) => apiFetch('/ai/find-relationships', {
    method: 'POST', body: JSON.stringify(nodeIds || []),
  }),
  analyzeAll: () => apiFetch('/ai/analyze-all', { method: 'POST' }),
  extractSubTopics: (id) => apiFetch(`/ai/extract-subtopics/${id}`, { method: 'POST' }),
  getSettings: () => apiFetch('/ai/settings'),
  saveSettings: (data) => apiFetch('/ai/settings', { method: 'POST', body: JSON.stringify(data) }),

  getTags: () => apiFetch('/tags'),
  createTag: (data) => apiFetch('/tags', { method: 'POST', body: JSON.stringify(data) }),
  deleteTag: (id) => apiFetch(`/tags/${id}`, { method: 'DELETE' }),

  getRelationships: () => apiFetch('/relationships'),
  createRelationship: (data) => apiFetch('/relationships', { method: 'POST', body: JSON.stringify(data) }),
  deleteRelationship: (id) => apiFetch(`/relationships/${id}`, { method: 'DELETE' }),

  // Chat APIs
  getConversations: () => apiFetch('/chat/conversations'),
  getConversation: (id) => apiFetch(`/chat/conversations/${id}`),
  createConversation: (data = {}) => apiFetch('/chat/conversations', { method: 'POST', body: JSON.stringify(data) }),
  sendMessage: (conversationId, content, aiSearch = false) => apiFetch(`/chat/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ content, ai_search: aiSearch }) }),
  saveToKB: (data) => apiFetch('/chat/save-to-kb', { method: 'POST', body: JSON.stringify(data) }),
}
