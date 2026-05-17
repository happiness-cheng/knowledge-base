import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useAppStore from '../../stores/appStore'
import { api } from '../../api/client'
import toast from 'react-hot-toast'

export default function NoteEditor({ onSaved }) {
  const { editingNode, closeEditor } = useAppStore()
  const [title, setTitle] = useState(editingNode?.title || '')
  const [content, setContent] = useState(editingNode?.content || '')
  const [tags, setTags] = useState(editingNode?.tags?.join(', ') || '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setTitle(editingNode?.title || '')
    setContent(editingNode?.content || '')
    setTags(editingNode?.tags?.join(', ') || '')
  }, [editingNode?.id])

  const handleSave = async () => {
    if (!title.trim() || !content.trim()) {
      toast.error('标题和内容不能为空')
      return
    }
    setSaving(true)
    try {
      const tagList = tags.split(',').map(t => t.trim()).filter(Boolean)
      if (editingNode?.id) {
        await api.updateNode(editingNode.id, { title, content, tags: tagList })
      } else {
        await api.createNode({ title, content, tags: tagList })
      }
      toast.success(editingNode?.id ? '已更新！' : '已创建！')
      onSaved()
      closeEditor()
    } catch (e) {
      toast.error('保存失败: ' + e.message)
    }
    setSaving(false)
  }

  return (
    <div className="modal-overlay" onClick={closeEditor} style={{ zIndex: 9999 }}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{editingNode?.id ? '编辑知识' : '新建知识'}</h2>
          <button className="panel-close" onClick={closeEditor}>×</button>
        </div>
        <div className="modal-body">
          <input className="editor-title" placeholder="标题..." value={title} onChange={e => setTitle(e.target.value)} />
          <input className="editor-title" placeholder="标签（用逗号分隔）..." value={tags} onChange={e => setTags(e.target.value)} style={{ fontSize: 14 }} />
          <div className="editor-container">
            <div className="editor-pane">
              <textarea placeholder="在这里写 Markdown..." value={content} onChange={e => setContent(e.target.value)} />
            </div>
            <div className="preview-pane">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || '*预览区域*'}</ReactMarkdown>
            </div>
          </div>
          <div className="panel-actions" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</button>
            <button className="btn" onClick={closeEditor}>取消</button>
          </div>
        </div>
      </div>
    </div>
  )
}