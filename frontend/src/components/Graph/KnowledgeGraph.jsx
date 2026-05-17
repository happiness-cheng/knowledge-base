import { useRef, useState, useEffect, useCallback } from 'react'
import useAppStore from '../../stores/appStore'
import { api } from '../../api/client'

const COLORS = {
  Technology: '#3b82f6', Science: '#22c55e', Mathematics: '#f59e0b',
  Philosophy: '#a855f7', Business: '#ef4444', Personal: '#ec4899', Other: '#6366f1',
}

export default function KnowledgeGraph({ onTopicClick }) {
  const { graphData, selectNode, selectedNodeId } = useAppStore()
  const containerRef = useRef()
  const [dims, setDims] = useState({ w: 1000, h: 700 })
  const [positions, setPositions] = useState({})
  const [dragId, setDragId] = useState(null)
  const dragRef = useRef({ mx: 0, my: 0, ox: 0, oy: 0 })
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const [panning, setPanning] = useState(false)
  const panRef = useRef({ mx: 0, my: 0, ox: 0, oy: 0 })
  const [subTopics, setSubTopics] = useState({})
  const [loadingSub, setLoadingSub] = useState(null)
  const velocitiesRef = useRef({})
  const animRef = useRef(null)
  const simRunningRef = useRef(false)
  const nodes = graphData.nodes || []
  const links = graphData.links || []
  useEffect(() => {
    const currentIds = new Set(nodes.map(n => String(n.id)))
    setSubTopics(prev => {
      const next = {}
      for (const [pid, data] of Object.entries(prev)) {
        if (currentIds.has(pid)) next[pid] = data
      }
      return Object.keys(next).length === Object.keys(prev).length ? prev : next
    })
  }, [nodes])
  const neighborMap = useCallback(() => {
    const map = {}
    links.forEach(lk => {
      if (!map[lk.source]) map[lk.source] = new Set()
      if (!map[lk.target]) map[lk.target] = new Set()
      map[lk.source].add(lk.target)
      map[lk.target].add(lk.source)
    })
    return map
  }, [links])
  const degreeMap = useCallback(() => {
    const map = {}
    links.forEach(lk => {
      map[lk.source] = (map[lk.source] || 0) + 1
      map[lk.target] = (map[lk.target] || 0) + 1
    })
    return map
  }, [links])
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      const h = entry.contentRect.height
      if (w > 0 && h > 0) setDims({ w, h })
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  useEffect(() => {
    if (!nodes.length || dims.w < 100 || dims.h < 100) return
    setPositions(prev => {
      const next = { ...prev }
      const cx = dims.w / 2
      const cy = dims.h / 2
      const base = Math.min(dims.w, dims.h) * 0.32
      const radius = base * Math.sqrt(Math.max(1, nodes.length / 8))
      nodes.forEach((n, i) => {
        if (!next[n.id]) {
          const angle = -Math.PI / 2 + (2 * Math.PI * i) / nodes.length
          next[n.id] = {
            x: cx + radius * Math.cos(angle) + (Math.random() - 0.5) * 30,
            y: cy + radius * Math.sin(angle) + (Math.random() - 0.5) * 30,
          }
        }
      })
      return next
    })
    if (!simRunningRef.current) {
      simRunningRef.current = true
      runForceSimulation()
    }
  }, [nodes.length, dims.w, dims.h])
  const runForceSimulation = useCallback(() => {
    if (animRef.current) cancelAnimationFrame(animRef.current)
    const velocities = velocitiesRef.current
    let energy = Infinity
    let iteration = 0
    const maxIterations = 300
    const coolingFactor = 0.98
    const step = () => {
      if (iteration >= maxIterations || energy < 0.5) { simRunningRef.current = false; return }
      const currentNodes = graphData.nodes || []
      const currentLinks = graphData.links || []
      if (!currentNodes.length) { simRunningRef.current = false; return }
      const cx = dims.w / 2, cy = dims.h / 2
      const k = Math.sqrt((dims.w * dims.h) / Math.max(1, currentNodes.length)) * 0.8
      const temp = Math.max(1, 50 * Math.pow(coolingFactor, iteration))
      currentNodes.forEach(n => { if (!velocities[n.id]) velocities[n.id] = { x: 0, y: 0 } })
      const posSnapshot = {}
      currentNodes.forEach(n => { posSnapshot[n.id] = positions[n.id] || { x: cx, y: cy } })
      const forces = {}
      currentNodes.forEach(n => { forces[n.id] = { x: 0, y: 0 } })
      for (let i = 0; i < currentNodes.length; i++) {
        for (let j = i + 1; j < currentNodes.length; j++) {
          const a = posSnapshot[currentNodes[i].id], b = posSnapshot[currentNodes[j].id]
          if (!a || !b) continue
          const dx = a.x - b.x, dy = a.y - b.y
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
          const force = (k * k) / dist
          const fx = (dx / dist) * force, fy = (dy / dist) * force
          forces[currentNodes[i].id].x += fx; forces[currentNodes[i].id].y += fy
          forces[currentNodes[j].id].x -= fx; forces[currentNodes[j].id].y -= fy
        }
      }
      currentLinks.forEach(lk => {
        const a = posSnapshot[lk.source], b = posSnapshot[lk.target]
        if (!a || !b) return
        const dx = b.x - a.x, dy = b.y - a.y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const force = (dist * dist) / k
        const fx = (dx / dist) * force * 0.5, fy = (dy / dist) * force * 0.5
        forces[lk.source].x += fx; forces[lk.source].y += fy
        forces[lk.target].x -= fx; forces[lk.target].y -= fy
      })
      currentNodes.forEach(n => {
        const p = posSnapshot[n.id]
        if (!p) return
        forces[n.id].x += (cx - p.x) * 0.01
        forces[n.id].y += (cy - p.y) * 0.01
      })
      energy = 0
      setPositions(prev => {
        const next = { ...prev }
        currentNodes.forEach(n => {
          if (dragId === n.id) return
          const f = forces[n.id]
          if (!f) return
          const mag = Math.sqrt(f.x * f.x + f.y * f.y)
          if (mag < 0.001) return
          const clampedMag = Math.min(mag, temp)
          const vx = (f.x / mag) * clampedMag, vy = (f.y / mag) * clampedMag
          const old = next[n.id] || posSnapshot[n.id]
          next[n.id] = { x: Math.max(30, Math.min(dims.w - 30, old.x + vx)), y: Math.max(30, Math.min(dims.h - 30, old.y + vy)) }
          energy += vx * vx + vy * vy
        })
        return next
      })
      iteration++
      animRef.current = requestAnimationFrame(step)
    }
    animRef.current = requestAnimationFrame(step)
  }, [positions, dims, dragId, graphData])
  useEffect(() => {
    if (nodes.length > 0 && links.length > 0) {
      if (!simRunningRef.current) { simRunningRef.current = true; runForceSimulation() }
    }
  }, [links.length])
  useEffect(() => { return () => { if (animRef.current) cancelAnimationFrame(animRef.current) } }, [])
  const onWheel = useCallback((e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    setTransform(prev => {
      const newScale = Math.max(0.2, Math.min(3, prev.scale * delta))
      const rect = containerRef.current.getBoundingClientRect()
      const mx = e.clientX - rect.left, my = e.clientY - rect.top
      return { scale: newScale, x: mx - (mx - prev.x) * (newScale / prev.scale), y: my - (my - prev.y) * (newScale / prev.scale) }
    })
  }, [])
  useEffect(() => { const el = containerRef.current; if (!el) return; el.addEventListener('wheel', onWheel, { passive: false }); return () => el.removeEventListener('wheel', onWheel) }, [onWheel])
  const onDown = useCallback((e, id) => { const p = positions[id] || { x: 0, y: 0 }; dragRef.current = { mx: e.clientX, my: e.clientY, ox: p.x, oy: p.y }; setDragId(id) }, [positions])
  const onBgDown = useCallback((e) => { if (e.target.closest('[data-node-id]')) return; panRef.current = { mx: e.clientX, my: e.clientY, ox: transform.x, oy: transform.y }; setPanning(true) }, [transform])
  const onMove = useCallback((e) => {
    if (dragId) { const { mx, my, ox, oy } = dragRef.current; setPositions(prev => ({ ...prev, [dragId]: { x: ox + (e.clientX - mx) / transform.scale, y: oy + (e.clientY - my) / transform.scale } })) }
    else if (panning) { const { mx, my, ox, oy } = panRef.current; setTransform(prev => ({ ...prev, x: ox + e.clientX - mx, y: oy + e.clientY - my })) }
  }, [dragId, panning, transform.scale])
  const onUp = useCallback(() => { const wasDragging = dragId !== null; setDragId(null); setPanning(false); if (wasDragging && !simRunningRef.current) { simRunningRef.current = true; runForceSimulation() } }, [dragId, runForceSimulation])
  const handleNodeClick = useCallback(async (node) => {
    selectNode(node.id)
    if (subTopics[node.id]) {
      setSubTopics(prev => { const next = { ...prev }; delete next[node.id]; return next })
      setPositions(prev => { const next = { ...prev }; Object.keys(next).forEach(k => { if (String(k).startsWith(`sub_${node.id}_`)) delete next[k] }); return next })
      return
    }
    setLoadingSub(node.id)
    try {
      const resp = await api.extractSubTopics(node.id)
      const topics = resp.sub_topics || [], relations = resp.relations || []
      setSubTopics(prev => ({ ...prev, [node.id]: { topics, relations } }))
      const parentPos = positions[node.id] || { x: dims.w / 2, y: dims.h / 2 }
      const childRadius = 80 + topics.length * 15
      const childPositions = {}
      const startAngle = Math.random() * Math.PI * 2
      topics.forEach((sub, i) => { const childId = `sub_${node.id}_${i}`; const angle = startAngle + (2 * Math.PI * i) / topics.length; childPositions[childId] = { x: parentPos.x + childRadius * Math.cos(angle), y: parentPos.y + childRadius * Math.sin(angle) } })
      setPositions(prev => ({ ...prev, ...childPositions }))
    } catch (e) { console.error('Failed to extract sub-topics:', e); setSubTopics(prev => ({ ...prev, [node.id]: { topics: [], relations: [] } })) }
    setLoadingSub(null)
  }, [positions, dims, subTopics])
  if (!nodes.length) return (<div ref={containerRef} className="main-area" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}><div className="empty-state"><div className="empty-state-icon"> </div><div>导入笔记或新建知识，知识图谱将在这里展示</div></div></div>)
  const neighbors = neighborMap(), degrees = degreeMap(), selectedNeighbors = selectedNodeId ? (neighbors[selectedNodeId] || new Set()) : new Set()
  const allItems = []
  nodes.forEach(n => { allItems.push({ ...n, isMain: true }) })
  const nodeIds = new Set(nodes.map(n => n.id))
  Object.entries(subTopics).forEach(([parentId, data]) => { if (!nodeIds.has(Number(parentId))) return; (data.topics || []).forEach((sub, i) => { allItems.push({ id: `sub_${parentId}_${i}`, title: typeof sub === 'string' ? sub : sub.title || sub.name || String(sub), category: nodes.find(n => n.id === Number(parentId))?.category || 'Other', isMain: false, parentId: Number(parentId) }) }) })
  const arrows = links.map((lk, i) => { const s = positions[lk.source], t = positions[lk.target]; if (!s || !t) return null; const label = lk.source_topic && lk.target_topic ? `${lk.source_topic} ↔ ${lk.target_topic}` : null; const isRelated = selectedNodeId && (lk.source === selectedNodeId || lk.target === selectedNodeId); const dimmed = selectedNodeId && !isRelated; return <Arrow key={`link_${i}`} s={s} t={t} color={dimmed ? 'rgba(129,140,248,0.15)' : 'rgba(129,140,248,0.8)'} bidirectional label={label} /> })
  const subArrows = Object.entries(subTopics).filter(([parentId]) => nodeIds.has(Number(parentId))).map(([parentId, data]) => { const topics = data.topics || [], relations = data.relations || [], result = []; topics.forEach((sub, i) => { const s = positions[parentId], t = positions[`sub_${parentId}_${i}`]; if (s && t) result.push(<Arrow key={`sub_link_${parentId}_${i}`} s={s} t={t} color="rgba(74,222,128,0.5)" dashed thin />) }); relations.forEach(([i, j], idx) => { const s = positions[`sub_${parentId}_${i}`], t = positions[`sub_${parentId}_${j}`]; if (s && t) result.push(<Arrow key={`sub_rel_${parentId}_${idx}`} s={s} t={t} color="rgba(251,191,36,0.8)" bidirectional thin />) }); return result })
  const topicLinks = links.filter(lk => lk.source_topic && lk.target_topic).map((lk, idx) => { const srcData = subTopics[lk.source], tgtData = subTopics[lk.target]; if (!srcData || !tgtData) return null; const srcIdx = (srcData.topics || []).indexOf(lk.source_topic), tgtIdx = (tgtData.topics || []).indexOf(lk.target_topic); if (srcIdx < 0 || tgtIdx < 0) return null; const s = positions[`sub_${lk.source}_${srcIdx}`], t = positions[`sub_${lk.target}_${tgtIdx}`]; if (!s || !t) return null; return <Arrow key={`topic_link_${idx}`} s={s} t={t} color="rgba(251,191,36,0.9)" bidirectional thin /> })
  return (<div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden', cursor: panning ? 'grabbing' : 'grab' }} onMouseDown={onBgDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}><div style={{ position: 'absolute', transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`, transformOrigin: '0 0', width: '100%', height: '100%' }}><svg width="100%" height="100%" style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', overflow: 'visible' }}>{arrows}{subArrows}{topicLinks}</svg>{allItems.map(n => { const p = positions[n.id] || { x: dims.w / 2, y: dims.h / 2 }; const sel = n.id === selectedNodeId; const c = COLORS[n.category] || '#6366f1'; const isLoading = loadingSub === n.id; const degree = degrees[n.id] || 0; const isNeighbor = selectedNeighbors.has(n.id); const dimmed = selectedNodeId && !sel && !isNeighbor && n.isMain; const baseSize = n.isMain ? 10 : 6; const extraSize = Math.min(degree * 2, 10); const nodePadding = n.isMain ? `${10 + extraSize/2}px ${16 + extraSize}px` : '6px 12px'; return (<div key={n.id} data-node-id={n.id} title={n.title} onMouseDown={e => { e.stopPropagation(); onDown(e, n.id) }} onClick={() => { if (n.isMain) { handleNodeClick(n) } else { selectNode(n.parentId); if (onTopicClick) onTopicClick(n.title) } }} style={{ position: 'absolute', left: p.x, top: p.y, transform: 'translate(-50%, -50%)', padding: nodePadding, background: sel ? '#6366f1' : n.isMain ? 'rgba(15,23,42,0.95)' : 'rgba(15,23,42,0.8)', border: `2px solid ${sel ? '#fff' : n.isMain ? c : '#22c55e'}`, borderRadius: 8, cursor: dragId === n.id ? 'grabbing' : 'grab', userSelect: 'none', fontSize: n.isMain ? 13 : 11, fontWeight: 500, color: '#f1f5f9', boxShadow: sel ? '0 0 20px rgba(99,102,241,0.5)' : '0 2px 8px rgba(0,0,0,0.4)', zIndex: sel ? 10 : 1, maxWidth: n.isMain ? 200 : 160, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', opacity: isLoading ? 0.6 : dimmed ? 0.3 : 1, transition: 'opacity 0.3s' }}>{isLoading ? '...' : n.title}{n.isMain && !isLoading && (<span style={{ marginLeft: 6, fontSize: 10, opacity: 0.5 }}>{subTopics[n.id] ? `(${subTopics[n.id].topics.length})` : degree > 0 ? `(${degree})` : ''}</span>)}</div>)})}</div><div style={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 4, zIndex: 20 }}><button onClick={() => setTransform(prev => ({ ...prev, scale: Math.min(3, prev.scale * 1.2) }))} style={zoomBtnStyle}>+</button><button onClick={() => setTransform(prev => ({ ...prev, scale: Math.max(0.2, prev.scale * 0.8) }))} style={zoomBtnStyle}>-</button><button onClick={() => setTransform({ x: 0, y: 0, scale: 1 })} style={zoomBtnStyle} title="Reset">R</button></div><div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)', color: 'rgba(255,255,255,0.3)', fontSize: 12, zIndex: 20 }}>滚轮缩放 · 拖拽平移 · 点击节点展开子知识点</div></div>)}
function Arrow({ s, t, color = 'rgba(129,140,248,0.8)', dashed = false, bidirectional = false, thin = false, label = null }) {
  const dx = t.x - s.x, dy = t.y - s.y
  const len = Math.hypot(dx, dy)
  if (len < 10) return null
  const ux = dx / len, uy = dy / len
  const offset = thin ? 30 : 50, yOff = thin ? 12 : 18
  const x1 = s.x + ux * offset, y1 = s.y + uy * yOff, x2 = t.x - ux * offset, y2 = t.y - uy * yOff
  const a = Math.atan2(dy, dx), hl = thin ? 8 : 12, lw = thin ? 1.5 : 3, glow = thin ? 4 : 8
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2
  return (<g><line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={glow} strokeLinecap="round" opacity="0.2" strokeDasharray={dashed ? '8,8' : 'none'} /><line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={lw} strokeLinecap="round" strokeDasharray={dashed ? '8,8' : 'none'} /><polygon points={`${x2},${y2} ${x2 - hl * Math.cos(a - 0.5)},${y2 - hl * Math.sin(a - 0.5)} ${x2 - hl * Math.cos(a + 0.5)},${y2 - hl * Math.sin(a + 0.5)}`} fill={color} />{bidirectional && (<polygon points={`${x1},${y1} ${x1 + hl * Math.cos(a - 0.5)},${y1 + hl * Math.sin(a - 0.5)} ${x1 + hl * Math.cos(a + 0.5)},${y1 + hl * Math.sin(a + 0.5)}`} fill={color} />)}{label && (<text x={mx} y={my - 8} textAnchor="middle" fill="rgba(255,255,255,0.6)" fontSize={10}>{label}</text>)}</g>)}
const zoomBtnStyle = { width: 32, height: 32, borderRadius: 6, border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(15,23,42,0.9)', color: '#f1f5f9', fontSize: 16, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }