import { useEffect, useState } from 'react'
import { auth } from '../../api/auth'

async function get(path) {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${auth.getToken() || ''}` } })
  if (!response.ok) {
    if (response.status === 401) throw new Error('请先返回笔记库登录，再打开公开资料演示。')
    throw new Error('公开演示暂不可用，请检查隔离服务是否启动。')
  }
  return response.json()
}

const styles = `
.public-demo{height:100vh;overflow-y:auto;background:#f5f2eb;color:#253b36;font-family:"Microsoft YaHei",sans-serif;padding:32px 5vw;box-sizing:border-box}
.public-demo *{box-sizing:border-box}.public-demo a{color:#236d59}.public-demo button{cursor:pointer;font:inherit}
.public-demo header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #cbd1c5;padding-bottom:18px;gap:20px}
.public-demo h1{font-family:"SimSun",serif;font-size:36px;margin:22px 0 10px}.public-demo h2{font-size:18px;margin:0 0 16px}
.public-demo p{line-height:1.8}.public-demo .eyebrow{letter-spacing:2px;font-size:11px;color:#577465}
.public-demo .intro{max-width:820px;color:#52675c}.public-demo .workspace{display:grid;grid-template-columns:260px minmax(0,1fr);gap:28px;margin-top:28px}
.public-demo .case{display:block;text-align:left;width:100%;background:transparent;border:1px solid #d1d8cd;border-radius:6px;padding:12px;margin-bottom:8px;color:inherit;line-height:1.6}
.public-demo .case[aria-pressed=true]{background:#dce8dd;border-color:#26715c}.public-demo .case small{display:block;color:#5e7568;font-size:11px;margin-bottom:4px}
.public-demo .panel{background:#fffdf8;border:1px solid #d8dbd1;border-radius:8px;padding:22px;margin-bottom:18px}
.public-demo .label{display:inline-block;color:#20684f;background:#e2ede2;border-radius:4px;padding:5px 8px;font-size:12px;margin-bottom:14px}
.public-demo .warning{color:#80521c;background:#f5ebd4;border:1px solid #e2d1a8;padding:12px;line-height:1.6;margin-top:12px}
.public-demo .answer{white-space:pre-wrap;line-height:1.9;font-size:15px}.public-demo .citation{border:0;background:#e5eee4;color:#216049;padding:3px 7px;border-radius:4px;margin:0 3px}
.public-demo form{display:flex;gap:10px}.public-demo input{min-width:0;flex:1;padding:12px;border:1px solid #9eafa1;border-radius:5px;background:white;font:inherit}
.public-demo .submit{background:#246a55;color:white;padding:10px 16px;border:0;border-radius:5px}.public-demo button:disabled{opacity:.5;cursor:wait}
.public-demo .evidence{border-top:1px solid #ddd;padding:16px 0;scroll-margin-top:24px}.public-demo .evidence h3{font-size:15px;margin:0 0 8px}
.public-demo pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.8 "Microsoft YaHei",sans-serif;margin:12px 0;color:#425849}
.public-demo details{margin-top:20px}.public-demo summary{cursor:pointer}.public-demo .meta{font-size:12px;color:#647669;line-height:1.8}
.public-demo .error{color:#a33024}.public-demo footer{margin-top:24px;border-top:1px solid #cbd1c5;padding-top:16px;font-size:12px;color:#647669}
@media(max-width:800px){.public-demo{padding:20px}.public-demo .workspace{grid-template-columns:1fr}.public-demo .cases{display:grid;grid-template-columns:1fr 1fr;gap:8px}.public-demo h1{font-size:28px}.public-demo form{flex-direction:column}}
`

export default function PublicDemo() {
  const [catalog, setCatalog] = useState(null)
  const [result, setResult] = useState(null)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    get('/api/demo/public').then(data => { if (active) setCatalog(data) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [])

  async function show(path) {
    setBusy(true)
    setError('')
    setResult(null)
    try { setResult(await get(path)) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  function jump(nodeId) {
    document.getElementById(`evidence-${nodeId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function answerText(text) {
    return text.split(/(\[doc:\d+\])/g).map((part, index) => {
      const citation = part.match(/^\[doc:(\d+)\]$/)
      return citation ? <button className="citation" key={index} onClick={() => jump(Number(citation[1]))}>
        资料 {citation[1]}
      </button> : part
    })
  }

  return <main className="public-demo">
    <style>{styles}</style>
    <header><span className="eyebrow">KNOWLEDGE / PUBLIC SOURCES</span><a href="/">返回笔记库</a></header>
    <h1>从问题到证据</h1>
    <p className="intro">五篇官方资料的中文导读，覆盖分布式计算、CUDA、Python、PyTorch 与 Kubernetes。
      固定问题展示已完成的 DeepSeek 回答记录；自由输入执行本地检索，不会生成新回答。</p>
    <div className="workspace">
      <aside><h2>选择一段回答记录</h2><div className="cases">
        {catalog?.cases.map(item => <button className="case" key={item.case_id} disabled={busy}
          aria-pressed={result?.case_id === item.case_id}
          onClick={() => show(`/api/demo/public/replay/${encodeURIComponent(item.case_id)}`)}>
          <small>{item.case_id.startsWith('U') ? '用户原问题' : '模拟缺证据问题'} · {item.case_id}</small>{item.question}
        </button>)}
      </div><p className="meta">5 篇导读 · 10 个片段<br />根据问题选择的主题，非独立盲测。<br />来源为编辑导读，非官方全文副本。</p></aside>
      <section>
        <div className="panel"><h2>试试自己的问题</h2>
          <form onSubmit={event => { event.preventDefault(); if (query.trim()) show(`/api/demo/public/search?query=${encodeURIComponent(query.trim())}`) }}>
            <input aria-label="公开资料检索问题" maxLength={1000} value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：yield 与 return 有什么区别？" />
            <button className="submit" disabled={busy || !catalog || !query.trim()}>本地检索</button>
          </form>
          <p className="meta">只检索这个独立公开库，不调用模型、不查询私人笔记。</p>
        </div>
        {error && <p role="alert" className="error">{error}</p>}
        {busy && <p role="status">正在读取证据…</p>}
        {!result && !busy && !error && <div className="panel"><p>从左侧选择问题查看回答与引用，或输入新问题检查检索片段。</p></div>}
        {result && <>
          <article className="panel" aria-label="回答与模式">
            <span className="label">{result.mode === 'recorded_model_answer' ? '真实模型回答回放 · 本次未调用模型' : '实时本地检索 · 未生成回答'}</span>
            <h2>{result.question}</h2>
            {result.answer ? <>
              <div className="answer">{answerText(result.answer.content.replace(/^NOT_FOUND_IN_KB:\s*/, ''))}</div>
              {result.answer.answer_status === 'not_found' && <p className="meta">状态：未找到支持证据 · 没有引用</p>}
              {result.review_note && <p className="warning">人工复核：{result.review_note}</p>}
            </> : <p>下面是当前检索片段。相似度不代表这些片段一定能回答问题；本页没有为这个新问题调用模型。</p>}
          </article>
          <section className="panel" aria-label="检索证据"><h2>{result.mode === 'recorded_model_answer' ? '当时返回的检索证据' : '本次检索证据'}</h2>
            {result.evidence.map((item, index) => <div className="evidence" id={result.evidence.findIndex(e => e.node_id === item.node_id) === index ? `evidence-${item.node_id}` : undefined} key={`${item.node_id}-${index}`}>
              <h3>资料 {item.node_id} · {item.title}</h3><div className="meta">片段：{item.heading} · L2 距离 {item.distance.toFixed(3)}</div>
              <pre>{item.content}</pre><a href={item.source_url} target="_blank" rel="noopener noreferrer">查看官方来源 ↗</a>
            </div>)}
          </section>
        </>}
        <details className="panel"><summary>查看语料来源与版本</summary>
          {catalog?.documents.map(doc => <div className="evidence" key={doc.node_id}>
            <h3>{doc.title}</h3><a href={doc.source_url} target="_blank" rel="noopener noreferrer">官方来源 ↗</a>
            <p className="meta">章节：{doc.source_section}<br />版本：{doc.source_version}<br />核对日期：{doc.checked_at}</p>
            <pre>{doc.content}</pre>
          </div>)}
        </details>
      </section>
    </div>
    <footer>公开资料演示 · 原笔记库保留 · 回放不等于本次实时生成 · 引用合法不等于每句话均正确</footer>
  </main>
}
