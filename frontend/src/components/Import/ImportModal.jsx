import { useState, useRef } from 'react'
import useAppStore from '../../stores/appStore'
import { api } from '../../api/client'
import toast from 'react-hot-toast'

export default function ImportModal({ onDone }) {
  const { closeImport } = useAppStore()
  const [files, setFiles] = useState([])
  const [results, setResults] = useState(null)
  const [importing, setImporting] = useState(false)
  const [textInput, setTextInput] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const fileRef = useRef()

  const handleDrop = (e) => { e.preventDefault(); setFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]) }
  const handleFileSelect = (e) => { setFiles(prev => [...prev, ...Array.from(e.target.files)]) }

  const handleImport = async () => {
    if (files.length === 0 && !textInput.trim()) { toast.error('请选择文件或粘贴文本'); return }
    setImporting(true)
    try {
      let result
      if (files.length > 0) { result = files.length === 1 ? await api.importFile(files[0]) : await api.importBatch(files) }
      if (textInput.trim()) { const textResult = await api.importText(textInput, textTitle || 'Pasted Note'); result = result ? { ...result, textResult } : textResult }
      setResults(result); toast.success('导入完成！'); onDone()
    } catch (e) { toast.error('导入失败: ' + e.message) }
    setImporting(false)
  }

  return (
    <div className="modal-overlay" onClick={closeImport} style={{ zIndex: 9999 }}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header"><h2>导入笔记</h2><button className="panel-close" onClick={closeImport}>×</button></div>
        <div className="modal-body">
          <div className="drop-zone" onDragOver={e => e.preventDefault()} onDrop={handleDrop} onClick={() => fileRef.current?.click()}>
            <div className="drop-zone-icon"> </div>
            <div className="drop-zone-text">拖放 .md、.txt、.docx 文件到这里，或点击选择</div>
            <input ref={fileRef} type="file" multiple accept=".md,.txt,.docx" style={{ display: 'none' }} onChange={handleFileSelect} />
          </div>
          {files.length > 0 && (<div className="import-progress">{files.map((f, i) => (<div key={i} className="import-file-item"><span>{f.name}</span><span>{(f.size / 1024).toFixed(1)} KB</span></div>))}</div>)}
          <div style={{ margin: '20px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>— 或粘贴文本 —</div>
          <input className="editor-title" placeholder="粘贴笔记的标题..." value={textTitle} onChange={e => setTextTitle(e.target.value)} />
          <textarea className="editor-title" placeholder="在此粘贴 Markdown 内容..." value={textInput} onChange={e => setTextInput(e.target.value)} style={{ height: 120, fontFamily: 'monospace', resize: 'vertical' }} />
          <div className="panel-actions"><button className="btn btn-primary" onClick={handleImport} disabled={importing}>{importing ? '导入中...' : '导入'}</button><button className="btn" onClick={closeImport}>取消</button></div>
          {results && (<div className="import-progress" style={{ marginTop: 16 }}><div className="import-file-item" style={{ color: 'var(--success)' }}>已导入 {results.node_count || results.imported?.reduce((a, b) => a + b.node_count, 0) || 0} 条知识</div></div>)}
        </div>
      </div>
    </div>
  )
}