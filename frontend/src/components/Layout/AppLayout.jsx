import Sidebar from './Sidebar'
import KnowledgeGraph from '../Graph/KnowledgeGraph'
import NodeDetailPanel from '../Graph/NodeDetailPanel'
import GraphControls from '../Graph/GraphControls'
import ChatPanel from '../Chat/ChatPanel'
import useAppStore from '../../stores/appStore'

export default function AppLayout({ onRefresh }) {
  const { selectedNodeId } = useAppStore()

  return (
    <div className="app-layout">
      <Sidebar onRefresh={onRefresh} />
      <div className="main-area">
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
