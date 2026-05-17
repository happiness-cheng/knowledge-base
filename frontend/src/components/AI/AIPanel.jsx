import { useState } from 'react'
import useAppStore from '../../stores/appStore'
import { api } from '../../api/client'
import toast from 'react-hot-toast'

export default function AIPanel({ onDone }) {
  const { closeAIPanel, nodes } = useAppStore()
  const [analyzing, setAnalyzing] = useState(false)
  const [finding, setFinding] = useState(false)
  const [result, setResult] = useState(null)
  const [progress, setProgress] = useState('')

  const unanalyzed = nodes.filter(n => !n.ai_analyzed).length

  const handleAnalyzeAll = async () => {
    setAnalyzing(true)
    setProgress(`正在分析 ${unanalyzed} 条知识，每条约 15 秒，请耐心等待...`)
    setResult(null)
    try {
      const r = await api.analyzeAll()
      setResult({ type: 'analyze', data: r })
      onDone()
      toast.success(`已分析 ${r.analyzed} 条知识！`)
    } catch (e) {
      toast.error('分析失败: ' + e.message)
    }
    setAnalyzing(false)
    setProgress('')
  }

  const handleFindRelationships = async () => {
    setFinding(true)
    setProgress('正在分析知识关联，请稍候...')
    setResult(null)
    try {
      const r = await api.findRelationships()
      setResult({ type: 'relations', data: r })
      onDone()
      toast.success(`发现 ${r.count} 条关联！`)
    } catch (e) {
      toast.error('关联发现失败: ' + e.message)
    }
    setFinding(false)
    setProgress('')
  }

  const renderResult = () => {
    if (!result) return null

    if (result.type === 'analyze') {
      const { analyzed, total } = result.data
      return (
        <div className="ai-result-card">
          <h3>分析完成</h3>
          <p>成功分析 <strong>{analyzed}</strong> / {total} 条知识</p>
        </div>
      )
    }

    if (result.type === 'relations') {
      const { created, count } = result.data
      if (count === 0) {
        return (
          <div className="ai-result-card">
            <h3>关联发现</h3>
            <p style={{ color: 'var(--text-secondary)' }}>未发现新的关联，尝试先分析更多知识节点</p>
          </div>
        )
      }
      return (
        <div className="ai-result-card">
          <h3>发现 {count} 条关联</h3>
          {created.map(rel => (
            <div key={rel.id} className="relation-item">
              <span className="rel-source">{rel.source_title}</span>
              <span className="rel-arrow">↔</span>
              <span className="rel-target">{rel.target_title}</span>
              <span className="rel-label">{rel.label || rel.rel_type}</span>
            </div>
          ))}
        </div>
      )
    }

    return null
  }

  return (
    <div className="modal-overlay" onClick={closeAIPanel} style={{ zIndex: 9999 }}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>AI 分析</h2>
          <button className="panel-close" onClick={closeAIPanel}>×</button>
        </div>
        <div className="modal-body">
          <div style={{ marginBottom: 20 }}>
            <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
              使用 AI 分析知识节点，提取摘要、分类、标签，并发现知识之间的关联。
            </p>

            <div className="panel-section">
              <h3>分析知识</h3>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                {unanalyzed > 0
                  ? `${unanalyzed} 条知识待分析（每条约 15 秒）`
                  : '所有知识已分析完毕'}
              </p>
              <button
                className="btn btn-primary"
                onClick={handleAnalyzeAll}
                disabled={analyzing || unanalyzed === 0}
              >
                {analyzing ? '分析中...' : `全部分析 (${unanalyzed})`}
              </button>
            </div>

            <div className="panel-section" style={{ marginTop: 20 }}>
              <h3>发现关联</h3>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                分析知识节点之间的联系，自动在图谱上连线
              </p>
              <button
                className="btn btn-primary"
                onClick={handleFindRelationships}
                disabled={finding || nodes.length < 2}
              >
                {finding ? '发现中...' : '发现关联'}
              </button>
            </div>
          </div>

          {progress && (
            <div style={{ padding: '12px 0', color: 'var(--accent)', fontSize: 14 }}>
              <span style={{ animation: 'pulse 1.5s infinite' }}>{progress}</span>
            </div>
          )}

          {renderResult()}

          <div className="panel-actions" style={{ marginTop: 20 }}>
            <button className="btn" onClick={closeAIPanel}>关闭</button>
          </div>
        </div>
      </div>
    </div>
  )
}