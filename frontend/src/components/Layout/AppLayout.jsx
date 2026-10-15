import Sidebar from './Sidebar'
import KnowledgeGraph from '../Graph/KnowledgeGraph'
import NodeDetailPanel from '../Graph/NodeDetailPanel'
import GraphControls from '../Graph/GraphControls'
import ChatPanel from '../Chat/ChatPanel'
import useAppStore from '../../stores/appStore'
import { useEffect, useState } from 'react'

export default function AppLayout({ onRefresh }) {
  const { selectedNodeId } = useAppStore()
  const [publicDemoEnabled, setPublicDemoEnabled] = useState(false)
  useEffect(() => {
    let active = true
    fetch('/api/demo/status').then(response => response.ok ? response.json() : null)
      .then(status => { if (active) setPublicDemoEnabled(status?.public_demo_enabled === true) })
      .catch(() => {})
    return () => { active = false }
  }, [])

  return (
    <div className="app-layout">
      <Sidebar onRefresh={onRefresh} />
      <div className="main-area">
        {publicDemoEnabled && <a href="/public-demo" style={{ padding: '8px 16px', background: '#e2ede2', color: '#216049', fontSize: 13 }}>
          公开资料演示：回答回放与本地检索 →
        </a>}
        <GraphControls onRefresh={onRefresh} />
        <KnowledgeGraph />
        <ChatPanel />
      </div>
      {selectedNodeId && (
        <NodeDetailPanel onRefresh={onRefresh} />
      )}
    </div>
  )
}
