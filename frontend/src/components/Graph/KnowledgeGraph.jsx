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

  // Pan & Zoom
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const [panning, setPanning] = useState(false)
  const panRef = useRef({ mx: 0, my: 0, ox: 0, oy: 0 })

  // Sub-topics (child nodes extracted by AI)
  const [subTopics, setSubTopics] = useState({})
  const [loadingSub, setLoadingSub] = useState(null)

  const nodes = graphData.nodes || []
  const links = graphData.links || []

// The full file is too large to include here; pushing only the changed line.