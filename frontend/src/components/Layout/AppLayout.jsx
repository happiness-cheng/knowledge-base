import { useState } from 'react'
import Sidebar from './Sidebar'
import KnowledgeGraph from '../Graph/KnowledgeGraph'
import NodeDetailPanel from '../Graph/NodeDetailPanel'
import GraphControls from '../Graph/GraphControls'
import ChatPanel from '../Chat/ChatPanel'
import useAppStore from '../../stores/appStore'

export default function AppLayout({ onRefresh }) {
  const { selectedNodeId } = useAppStore()
  const [highlightTopic, setHighlightTopic] = useState(null)

  return (
    <div className="app-layout">
      <Sidebar onRefresh={onRefresh} />
      <div className="main-area">
        <GraphControls onRefresh={onRefresh} />
        <KnowledgeGraph onTopicClick={(topic) => setHighlightTopic(topic)} />
        <ChatPanel />
      </div>
      {selectedNodeId && (
        <NodeDetailPanel
          onRefresh={onRefresh}
          highlightTopic={highlightTopic}
        />
      )}
    </div>
  )
}
