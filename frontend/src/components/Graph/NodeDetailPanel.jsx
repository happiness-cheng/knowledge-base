import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useAppStore from '../../stores/appStore'
import { api } from '../../api/client'
import toast from 'react-hot-toast'

export default function NodeDetailPanel({ onRefresh }) {
  const { selectedNodeId, selectNode, openEditor, nodes, searchHighlight } = useAppStore()
  const [node, setNode] = useState(null)
  const [relationships, setRelationships] = useState([])
  const [analyzing, setAnalyzing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showAddRel, setShowAddRel] = useState(false)
  const [relTargetNodeId, setRelTargetNodeId] = useState('')
  const [relTargetSubtopics, setRelTargetSubtopics] = useState([])
  const [relTargetTopic, setRelTargetTopic] = useState('')
  const [relSourceTopic, setRelSourceTopic] = useState('')
  const [sourceSubtopics, setSourceSubtopics] = useState([])
  const [suggestedLinks, setSuggestedLinks] = useState([])
  const [ignoredSuggestions, setIgnoredSuggestions] = useState(new Set())
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)
  const contentRef = useRef(null)

  const loadData = () => {
    if (!selectedNodeId) return
    api.getNode(selectedNodeId).then(setNode).catch(() => setNode(null))
    api.getRelationships().then(rels => {
      setRelationships(rels.filter(r => r.source_id === selectedNodeId || r.target_id === selectedNodeId))
    })
    // Load subtopics for this node
    api.getNodeSubtopics(selectedNodeId).then(d => setSourceSubtopics(d.subtopics || [])).catch(() => {})
    // Load suggested links
    setSuggestedLinks([])
    setIgnoredSuggestions(new Set())
    setLoadingSuggestions(true)
    api.getSuggestedLinks(selectedNodeId)
      .then(d => setSuggestedLinks(d.suggestions || []))
      .catch(() => {})
      .finally(() => setLoadingSuggestions(false))
  }

  useEffect(() => { loadData() }, [selectedNodeId])

  // Scroll to and highlight search term (waits for content to render)
  useEffect(() => {
    if (!searchHighlight || !node?.content) return

    const tryHighlight = () => {
      const container = contentRef.current
      if (!container) return false
      const text = searchHighlight.toLowerCase()

      // 先找标题
      const headings = container.querySelectorAll('h1, h2, h3')
      for (const h of headings) {
        if (h.textContent.toLowerCase().includes(text)) {
          h.scrollIntoView({ behavior: 'smooth', block: 'center' })
          h.style.background = 'rgba(99, 102, 241, 0.3)'
          h.style.borderRadius = '4px'
          h.style.padding = '2px 8px'
          h.style.transition = 'background 0.3s'
          setTimeout(() => { h.style.background = 'transparent' }, 3000)
          return true
        }
      }

      // 标题没找到，在所有文本节点中找
      const allElements = container.querySelectorAll('p, li, td')
      for (const el of allElements) {
        if (el.textContent.toLowerCase().includes(text)) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' })
          el.style.background = 'rgba(99, 102, 241, 0.2)'
          el.style.borderRadius = '4px'
          el.style.transition = 'background 0.3s'
          setTimeout(() => { el.style.background = 'transparent' }, 3000)
          return true
        }
      }
      return false
    }

    // ReactMarkdown 需要一帧来渲染，重试几次
    if (!tryHighlight()) {
      const timer1 = setTimeout(() => {
        if (!tryHighlight()) {
          setTimeout(tryHighlight, 500)
        }
      }, 200)
      return () => clearTimeout(timer1)
    }
  }, [searchHighlight, node?.id])

  // Load target node subtopics when target node is selected
  useEffect(() => {
    if (!relTargetNodeId) { setRelTargetSubtopics([]); setRelTargetTopic(''); return }
    api.getNodeSubtopics(relTargetNodeId).then(d => setRelTargetSubtopics(d.subtopics || [])).catch(() => {})
  }, [relTargetNodeId])

  const handleAnalyze = async () => {
    setAnalyzing(true)
    try {
      const result = await api.analyzeNode(selectedNodeId)
      setNode(prev => ({ ...prev, ...result }))
      onRefresh()
      toast.success('AI 分析完成！')
    } catch (e) {
      toast.error('分析失败: ' + e.message)
    }
    setAnalyzing(false)
  }

  const handleDelete = async () => {
    try {
      await api.deleteNode(selectedNodeId)
      selectNode(null)
      onRefresh()
      toast.success('已删除')
    } catch (e) {
      toast.error('删除失败: ' + e.message)
    }
    setConfirmDelete(false)
  }

  const handleAddRelationship = async () => {
    const targetId = Number(relTargetNodeId)
    if (!targetId || targetId === selectedNodeId) {
      toast.error('请选择一个不同的目标节点')
      return
    }
    try {
      const label = relSourceTopic && relTargetTopic
        ? `${relSourceTopic} ↔ ${relTargetTopic}`
        : null
      await api.createRelationship({
        source_id: selectedNodeId,
        target_id: targetId,
        source_topic: relSourceTopic || null,
        target_topic: relTargetTopic || null,
        rel_type: 'related_to',
        label,
      })
      toast.success('知识点关联已创建')
      setShowAddRel(false)
      setRelTargetNodeId('')
      setRelSourceTopic('')
      setRelTargetTopic('')
      loadData()
      onRefresh()
    } catch (e) {
      toast.error('创建失败: ' + e.message)
    }
  }

  const handleDeleteRelationship = async (relId) => {
    try {
      await api.deleteRelationship(relId)
      toast.success('关联已删除')
      loadData()
      onRefresh()
    } catch (e) {
      toast.error('删除失败: ' + e.message)
    }
  }

  const handleAcceptSuggestion = async (suggestion) => {
    try {
      await api.createRelationship({
        source_id: selectedNodeId,
        target_id: suggestion.target_id,
        rel_type: 'related_to',
        label: `关键词重叠: ${suggestion.shared_keywords?.slice(0, 3).join(', ')}`,
      })
      toast.success(`已关联: ${suggestion.target_title}`)
      setIgnoredSuggestions(prev => new Set([...prev, suggestion.target_id]))
      loadData()
      onRefresh()
    } catch (e) {
      toast.error('关联失败: ' + e.message)
    }
  }

  const handleIgnoreSuggestion = (targetId) => {
    setIgnoredSuggestions(prev => new Set([...prev, targetId]))
  }

  if (!node) return (
    <>
      <div className="drawer-backdrop" onClick={() => selectNode(null)} />
      <div className="node-detail-panel">
        <div className="panel-header">
          <h2>加载中...</h2>
          <button className="panel-close" onClick={() => selectNode(null)}>×</button>
        </div>
      </div>
    </>
  )

  const otherNodes = nodes.filter(n => n.id !== selectedNodeId)

  return (
    <>
      <div className="drawer-backdrop" onClick={() => selectNode(null)} />
      <div className="node-detail-panel">
        <div className="panel-header">
          <h2>{node.title}</h2>
          <button className="panel-close" onClick={() => selectNode(null)}>×</button>
        </div>
        <div className="panel-body">
          {node.category && (
            <div className="panel-section">
              <h3>分类</h3>
              <span className="panel-category">{node.category}</span>
            </div>
          )}

          {node.tags?.length > 0 && (
            <div className="panel-section">
              <h3>标签</h3>
              <div className="panel-tags">
                {node.tags.map(t => <span key={t} className="panel-tag">{t}</span>)}
              </div>
            </div>
          )}

          {node.summary && (
            <div className="panel-section">
              <h3>AI 摘要</h3>
              <p className="panel-summary">{node.summary}</p>
            </div>
          )}

          <div className="panel-section">
            <h3>内容</h3>
            <div className="panel-content" ref={contentRef}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{node.content}</ReactMarkdown>
            </div>
          </div>

          <div className="panel-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3>知识点关联</h3>
              <button className="btn btn-sm" onClick={() => setShowAddRel(!showAddRel)}>
                {showAddRel ? '取消' : '+ 添加关联'}
              </button>
            </div>

            {showAddRel && (
              <div className="add-rel-form">
                {/* Step 1: Select source topic (this node) */}
                {sourceSubtopics.length > 0 && (
                  <select value={relSourceTopic} onChange={e => setRelSourceTopic(e.target.value)}>
                    <option value="">本节点知识点（可选）...</option>
                    {sourceSubtopics.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                )}

                {/* Step 2: Select target node */}
                <select value={relTargetNodeId} onChange={e => setRelTargetNodeId(e.target.value)}>
                  <option value="">选择目标节点...</option>
                  {otherNodes.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
                </select>

                {/* Step 3: Select target subtopic */}
                {relTargetSubtopics.length > 0 && (
                  <select value={relTargetTopic} onChange={e => setRelTargetTopic(e.target.value)}>
                    <option value="">目标知识点（可选）...</option>
                    {relTargetSubtopics.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                )}

                <button className="btn btn-primary btn-sm" onClick={handleAddRelationship}>确认关联</button>
              </div>
            )}

            {relationships.length > 0 ? (
              <ul className="related-nodes">
                {relationships.map(r => {
                  const isSource = r.source_id === selectedNodeId
                  const relatedId = isSource ? r.target_id : r.source_id
                  const relatedNode = nodes.find(n => n.id === relatedId)
                  const displayName = relatedNode ? relatedNode.title : `节点 #${relatedId}`
                  const topicInfo = r.source_topic && r.target_topic
                    ? `${r.source_topic} ↔ ${r.target_topic}`
                    : r.source_topic || r.target_topic || ''
                  return (
                    <li key={r.id} className="related-node-item">
                      <span>
                        {isSource ? '→' : '←'} {displayName}
                        {topicInfo && <span className="rel-topic">{topicInfo}</span>}
                      </span>
                      <button className="btn-danger-inline" onClick={() => handleDeleteRelationship(r.id)} title="删除关联">删除</button>
                    </li>
                  )
                })}
              </ul>
            ) : !showAddRel && (
              <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>暂无关联</p>
            )}

            {/* Suggested links */}
            {!loadingSuggestions && suggestedLinks.filter(s => !ignoredSuggestions.has(s.target_id)).length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  建议关联（关键词匹配）
                </div>
                {suggestedLinks.filter(s => !ignoredSuggestions.has(s.target_id)).map(s => (
                  <div key={s.target_id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '6px 8px', borderRadius: 6, marginBottom: 4,
                    background: 'var(--bg-primary)', fontSize: 13,
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {s.target_title}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                        共同: {s.shared_keywords?.slice(0, 4).join(', ')}
                        <span style={{ marginLeft: 6, opacity: 0.6 }}>相似度 {Math.round(s.similarity * 100)}%</span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
                      <button className="btn btn-primary btn-sm" onClick={() => handleAcceptSuggestion(s)}>关联</button>
                      <button className="btn btn-sm" onClick={() => handleIgnoreSuggestion(s.target_id)}>忽略</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="panel-actions">
            <button className="btn btn-primary" onClick={handleAnalyze} disabled={analyzing}>
              {analyzing ? '分析中...' : 'AI 分析'}
            </button>
            <button className="btn" onClick={() => openEditor(node)}>编辑</button>
            {confirmDelete ? (
              <div className="confirm-delete">
                <button className="btn btn-danger" onClick={handleDelete}>确认删除</button>
                <button className="btn" onClick={() => setConfirmDelete(false)}>取消</button>
              </div>
            ) : (
              <button className="btn btn-danger" onClick={() => setConfirmDelete(true)}>删除</button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
