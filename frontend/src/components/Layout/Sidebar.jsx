import { useState, useMemo, useEffect, useRef } from 'react'
import useAppStore from '../../stores/appStore'
import { api } from '../../api/client'
import toast from 'react-hot-toast'

export default function Sidebar({ onRefresh }) {
  const { nodes, tags, relationships, sidebarFilter, setFilter, selectNode, selectedNodeId, openEditor, openImport, openAIPanel } = useAppStore()
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [showNewTag, setShowNewTag] = useState(false)
  const [newTagName, setNewTagName] = useState('')
  const [newTagColor, setNewTagColor] = useState('#6366f1')
  const [showAllTags, setShowAllTags] = useState(false)
  const debounceRef = useRef(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!search.trim()) { setSearchResults(null); setSearching(false); return }
    setSearching(true)
    debounceRef.current = setTimeout(async () => {
      try { setSearchResults(await api.getNodes({ search: search.trim() })) } catch (e) { console.error('Search failed:', e) }
      setSearching(false)
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [search])

  const displayNodes = searchResults !== null ? searchResults : nodes

  const { selectedNode, relatedNodes, unrelatedNodes } = useMemo(() => {
    if (!selectedNodeId) return { selectedNode: null, relatedNodes: [], unrelatedNodes: displayNodes }
    const relIds = new Set()
    relationships.forEach(r => { if (r.source_id === selectedNodeId) relIds.add(r.target_id); if (r.target_id === selectedNodeId) relIds.add(r.source_id) })
    return { selectedNode: displayNodes.find(n => n.id === selectedNodeId) || null, relatedNodes: displayNodes.filter(n => relIds.has(n.id)), unrelatedNodes: displayNodes.filter(n => n.id !== selectedNodeId && !relIds.has(n.id)) }
  }, [selectedNodeId, displayNodes, relationships])

  const applyFilters = (list) => list.filter(n => { if (sidebarFilter.tag && !n.tags?.includes(sidebarFilter.tag)) return false; return true })
  const filteredUnrelated = applyFilters(unrelatedNodes)
  const filteredRelated = applyFilters(relatedNodes)

  const handleSearch = (v) => { setSearch(v); setFilter({ search: v }) }

  const handleCreateTag = async () => {
    const name = newTagName.trim()
    if (!name) { toast.error('标签名不能为空'); return }
    try { await api.createTag({ name, color: newTagColor }); toast.success(`标签"${name}"已创建`); setNewTagName(''); setShowNewTag(false); onRefresh() } catch (e) { toast.error('创建失败: ' + e.message) }
  }

  const renderNode = (n, isRelated = false) => (
    <div key={n.id} className={`node-item ${selectedNodeId === n.id ? 'selected' : ''} ${isRelated ? 'node-item-related' : ''}`} onClick={() => selectNode(n.id)}>
      <div className="node-item-title">{n.title}</div>
      <div className="node-item-meta">{n.category && <span className="node-item-tag">{n.category}</span>}{n.tags?.slice(0, 3).map(t => <span key={t} className="node-item-tag">{t}</span>)}{isRelated && <span className="node-item-tag related-badge">关联</span>}</div>
    </div>
  )

  const showRelatedSection = selectedNodeId && (filteredRelated.length > 0 || selectedNode)

  return (
    <div className="sidebar">
      <div className="sidebar-header"><h1>我的知识库</h1><p>{nodes.length} 条知识 · {tags.length} 个标签</p></div>
      <div style={{ padding: '12px 20px', display: 'flex', gap: 8 }}>
        <button className="btn btn-primary" onClick={() => openEditor(null)}>+ 新建</button>
        <button className="btn" onClick={openImport}>导入</button>
        <button className="btn" onClick={openAIPanel}>AI分析</button>
      </div>
      <div className="search-bar"><input placeholder="搜索标题、内容、标签..." value={search} onChange={e => handleSearch(e.target.value)} />{searching && <span className="search-spinner" />}</div>
      {tags.length > 0 && (() => {
        const activeTags = tags.filter(t => t.node_count > 0).sort((a, b) => b.node_count - a.node_count)
        const visible = showAllTags ? activeTags : activeTags.slice(0, 15)
        if (activeTags.length === 0) return null
        return (<div className="tag-cloud">{visible.map(t => (<span key={t.id} className={`tag-chip ${sidebarFilter.tag === t.name ? 'active' : ''}`} onClick={() => setFilter({ tag: sidebarFilter.tag === t.name ? null : t.name })} style={t.color && t.color !== '#6366f1' ? { borderColor: t.color } : undefined}>{t.name}<span className="count">({t.node_count})</span></span>))}{activeTags.length > 15 && <span className="tag-chip" onClick={() => setShowAllTags(!showAllTags)} style={{ opacity: 0.6 }}>{showAllTags ? '收起' : `+${activeTags.length - 15} 更多`}</span>}<span className="tag-chip tag-chip-add" onClick={() => setShowNewTag(!showNewTag)}>+</span></div>)
      })()}
      {showNewTag && <div style={{ padding: '0 20px 8px', display: 'flex', gap: 6, alignItems: 'center' }}><input type="text" value={newTagName} onChange={e => setNewTagName(e.target.value)} placeholder="标签名" style={{ flex: 1, padding: '4px 8px', background: '#1e293b', border: '1px solid #334155', borderRadius: 4, color: '#f1f5f9', fontSize: 13 }} onKeyDown={e => e.key === 'Enter' && handleCreateTag()} /><input type="color" value={newTagColor} onChange={e => setNewTagColor(e.target.value)} style={{ width: 28, height: 28, border: 'none', background: 'none', cursor: 'pointer' }} /><button className="btn btn-sm btn-primary" onClick={handleCreateTag}>OK</button></div>}
      <div className="node-list">{displayNodes.length === 0 ? (<div className="empty-state"><div className="empty-state-icon"> </div><div>{search ? '没有找到匹配的知识' : '还没有知识，新建或导入一些吧！'}</div></div>) : showRelatedSection ? (<>{selectedNode && <><div className="sidebar-section-title">当前选中</div>{renderNode(selectedNode)}</>}{filteredRelated.length > 0 && <><div className="sidebar-section-title">关联知识 ({filteredRelated.length})</div>{filteredRelated.map(n => renderNode(n, true))}</>}{filteredUnrelated.length > 0 && <><div className="sidebar-section-title">其他知识</div>{filteredUnrelated.map(n => renderNode(n))}</>}</>) : applyFilters(displayNodes).map(n => renderNode(n))}</div>
    </div>
  )
}