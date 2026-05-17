import { useEffect, useState, useRef } from 'react'
import { Toaster } from 'react-hot-toast'
import AppLayout from './components/Layout/AppLayout'
import NoteEditor from './components/Editor/NoteEditor'
import ImportModal from './components/Import/ImportModal'
import AIPanel from './components/AI/AIPanel'
import useAppStore from './stores/appStore'
import { api } from './api/client'

export default function App() {
  const { setGraphData, setNodes, setTags, setRelationships, showEditor, showImport, showAIPanel } = useAppStore()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const timerRef = useRef(null)
  const retriesRef = useRef(0)

  const refresh = async () => {
    try {
      const [graph, nodes, tags, rels] = await Promise.all([
        api.getGraph(),
        api.getNodes(),
        api.getTags(),
        api.getRelationships(),
      ])
      setGraphData(graph)
      setNodes(nodes)
      setTags(tags)
      setRelationships(rels)
      setLoading(false)
      setLoadError(false)
      retriesRef.current = 0
    } catch (e) {
      retriesRef.current++
      if (retriesRef.current >= 5) {
        setLoading(false)
        setLoadError(true)
        return
      }
      timerRef.current = setTimeout(refresh, 3000)
    }
  }

  useEffect(() => {
    refresh()
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [])

  if (loadError) {
    return (
      <div style={{
        width: '100vw', height: '100vh', display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        background: '#0f172a', color: '#ef4444', gap: 16,
      }}>
        <div style={{ fontSize: 18 }}>无法连接后端服务</div>
        <div style={{ color: '#94a3b8', fontSize: 14 }}>请确保后端已启动（端口 8766）</div>
        <button
          onClick={() => { retriesRef.current = 0; setLoadError(false); setLoading(true); refresh() }}
          style={{ padding: '8px 24px', borderRadius: 8, border: '1px solid #6366f1', background: '#6366f1', color: '#fff', cursor: 'pointer', fontSize: 14 }}
        >
          重试连接
        </button>
      </div>
    )
  }

  if (loading) {
    return (
      <div style={{
        width: '100vw', height: '100vh', display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        background: '#0f172a', color: '#94a3b8', gap: 16,
      }}>
        <div style={{
          width: 40, height: 40, border: '3px solid #334155',
          borderTop: '3px solid #6366f1', borderRadius: '50%',
          animation: 'spin 1s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        <div>Waiting for backend...</div>
      </div>
    )
  }

  return (
    <>
      <AppLayout onRefresh={refresh} />
      {showEditor && <NoteEditor onSaved={refresh} />}
      {showImport && <ImportModal onDone={refresh} />}
      {showAIPanel && <AIPanel onDone={refresh} />}
      <Toaster position="bottom-right" />
    </>
  )
}