import { auth } from './auth'

const API_BASE = '/api'

async function apiFetch(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-cache',
    ...options.headers,
  }
  const token = auth.getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    headers,
    ...options,
  })
  if (res.status === 401) {
    auth.clearToken()
    window.location.reload()
    throw new Error('Unauthorized')
  }
  if (!res.ok) throw new Error(`API error: ${res.status} ${await res.text()}`)
  return res.json()
}

// 带 token 的 FormData 请求（用于文件上传）
async function apiFetchForm(path, formData, method = 'POST') {
  const headers = {}
  const token = auth.getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: formData })
  if (res.status === 401) {
    auth.clearToken()
    window.location.reload()
    throw new Error('Unauthorized')
  }
  if (!res.ok) throw new Error(`API error: ${res.status} ${await res.text()}`)
  return res.json()
}

export const api = {
  // Auth
  login: (username, password) => apiFetch('/auth/login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  }),
  register: (username, password) => apiFetch('/auth/register', {
    method: 'POST', body: JSON.stringify({ username, password }),
  }),
  getMe: () => apiFetch('/auth/me'),

  getNodes: (params = {}) => {
    const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v)))
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

  importFile: (file) => {
    const form = new FormData()
    form.append('file', file)
    return apiFetchForm('/import/file', form)
  },
  importBatch: (files) => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    return apiFetchForm('/import/batch', form)
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

  getConversations: () => apiFetch('/chat/conversations'),
  getConversation: (id) => apiFetch(`/chat/conversations/${id}`),
  createConversation: (data = {}) => apiFetch('/chat/conversations', { method: 'POST', body: JSON.stringify(data) }),
  sendMessage: (conversationId, content, aiSearch = false) => apiFetch(`/chat/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ content, ai_search: aiSearch }) }),
  saveToKB: (data) => apiFetch('/chat/save-to-kb', { method: 'POST', body: JSON.stringify(data) }),
}
