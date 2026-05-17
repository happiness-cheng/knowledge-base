import useAppStore from '../../stores/appStore'

export default function GraphControls({ onRefresh }) {
  const { graphData, toggleChatPanel } = useAppStore()

  return (
    <div className="graph-controls" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
      <button onClick={onRefresh}>刷新</button>
      <button onClick={toggleChatPanel} style={{ backgroundColor: '#2563eb', color: 'white' }}>
        Chat
      </button>
      <span style={{ padding: '8px 12px', fontSize: 13, color: 'var(--text-secondary)' }}>
        {graphData.nodes?.length || 0} 节点 · {graphData.links?.length || 0} 条关联
      </span>
    </div>
  )
}