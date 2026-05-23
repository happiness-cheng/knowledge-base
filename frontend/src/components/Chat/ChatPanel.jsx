import React, { useState, useEffect, useRef } from 'react';
import useAppStore from '../../stores/appStore';
import { api } from '../../api/client';

function SourceBadge({ nodeId }) {
  const selectNode = useAppStore(state => state.selectNode);
  return (
    <span
      onClick={() => selectNode(nodeId)}
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        margin: '0 2px',
        fontSize: 11,
        fontWeight: 600,
        color: '#1e40af',
        background: '#dbeafe',
        borderRadius: 12,
        cursor: 'pointer',
      }}
      title="Click to view source"
    >
      Source {nodeId}
    </span>
  );
}

function WebSourceBadge({ title, url }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        margin: '2px 2px',
        fontSize: 11,
        fontWeight: 600,
        color: '#92400e',
        background: '#fef3c7',
        borderRadius: 12,
        textDecoration: 'none',
        maxWidth: 200,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
      title={url}
    >
      {title || 'Web'}
    </a>
  );
}

// Markdown table renderer
function MarkdownTable({ lines }) {
  if (lines.length < 2) return null;
  const parseRow = (line) => line.split('|').slice(1, -1).map(cell => cell.trim());
  const headers = parseRow(lines[0]);
  // Skip separator line (line[1])
  const rows = lines.slice(2).map(parseRow);

  return (
    <div style={{ overflowX: 'auto', margin: '8px 0' }}>
      <table style={{
        width: '100%', borderCollapse: 'collapse', fontSize: 13,
        border: '1px solid #e2e8f0', borderRadius: 8,
      }}>
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} style={{
                padding: '6px 10px', background: '#f1f5f9', borderBottom: '2px solid #e2e8f0',
                textAlign: 'left', fontWeight: 600, color: '#334155', whiteSpace: 'nowrap',
              }}>{renderInline(h)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} style={{
                  padding: '6px 10px', borderBottom: '1px solid #e2e8f0',
                  color: '#475569',
                }}>{renderInline(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Render inline markdown (bold, code, source badges)
function renderInline(text) {
  if (!text) return null;
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[doc:\d+\])/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} style={{
        background: '#f1f5f9', padding: '1px 5px', borderRadius: 4,
        fontSize: 12, fontFamily: 'monospace',
      }}>{part.slice(1, -1)}</code>;
    }
    const docMatch = part.match(/\[doc:(\d+)\]/);
    if (docMatch) return <SourceBadge key={i} nodeId={parseInt(docMatch[1])} />;
    return part;
  });
}

function SimpleMarkdown({ text }) {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let tableLines = [];
  let i = 0;

  const flushTable = () => {
    if (tableLines.length >= 2) {
      elements.push(<MarkdownTable key={`table-${i}`} lines={tableLines} />);
    } else {
      tableLines.forEach((line, idx) => {
        elements.push(<div key={`tl-${i}-${idx}`}>{renderInline(line)}</div>);
      });
    }
    tableLines = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    // Table detection
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      tableLines.push(line);
      i++;
      continue;
    } else if (tableLines.length > 0) {
      flushTable();
    }

    // Header
    const h3 = line.match(/^### (.+)/);
    if (h3) {
      elements.push(<div key={i} style={{ fontSize: 15, fontWeight: 700, margin: '10px 0 4px', color: '#1e293b' }}>{renderInline(h3[1])}</div>);
      i++; continue;
    }
    const h2 = line.match(/^## (.+)/);
    if (h2) {
      elements.push(<div key={i} style={{ fontSize: 16, fontWeight: 700, margin: '12px 0 4px', color: '#1e293b' }}>{renderInline(h2[1])}</div>);
      i++; continue;
    }
    const h1 = line.match(/^# (.+)/);
    if (h1) {
      elements.push(<div key={i} style={{ fontSize: 18, fontWeight: 700, margin: '12px 0 6px', color: '#0f172a' }}>{renderInline(h1[1])}</div>);
      i++; continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      elements.push(<hr key={i} style={{ border: 'none', borderTop: '1px solid #e2e8f0', margin: '10px 0' }} />);
      i++; continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      elements.push(
        <div key={i} style={{
          borderLeft: '3px solid #cbd5e1', paddingLeft: 10, margin: '6px 0',
          color: '#64748b', fontStyle: 'italic',
        }}>{renderInline(line.slice(2))}</div>
      );
      i++; continue;
    }

    // List item
    const listMatch = line.match(/^[-*] (.+)/);
    if (listMatch) {
      elements.push(
        <div key={i} style={{ paddingLeft: 16, margin: '2px 0', position: 'relative' }}>
          <span style={{ position: 'absolute', left: 2, color: '#94a3b8' }}>•</span>
          {renderInline(listMatch[1])}
        </div>
      );
      i++; continue;
    }

    // Numbered list
    const numMatch = line.match(/^\d+\. (.+)/);
    if (numMatch) {
      const num = line.match(/^(\d+)\./)[1];
      elements.push(
        <div key={i} style={{ paddingLeft: 16, margin: '2px 0', position: 'relative' }}>
          <span style={{ position: 'absolute', left: 0, color: '#94a3b8', fontSize: 13 }}>{num}.</span>
          {renderInline(numMatch[1])}
        </div>
      );
      i++; continue;
    }

    // Empty line
    if (line.trim() === '') {
      elements.push(<div key={i} style={{ height: 6 }} />);
      i++; continue;
    }

    // Regular paragraph
    elements.push(<div key={i} style={{ margin: '2px 0' }}>{renderInline(line)}</div>);
    i++;
  }

  // Flush remaining table
  if (tableLines.length > 0) flushTable();

  return <>{elements}</>;
}

// Agent 推理步骤展示（可折叠）
function AgentSteps({ steps }) {
  const [expanded, setExpanded] = React.useState(false);

  if (!steps || steps.length === 0) return null;

  const toolCallCount = steps.filter(s => s.type === 'tool_call').length;

  return (
    <div style={{
      marginBottom: 8, fontSize: 12, color: '#64748b',
      background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0',
      overflow: 'hidden',
    }}>
      {/* 收起状态：摘要栏 */}
      <div onClick={() => setExpanded(!expanded)} style={{
        padding: '6px 12px', cursor: 'pointer', display: 'flex',
        alignItems: 'center', gap: 6, fontWeight: 500,
      }}>
        <span style={{ fontSize: 10 }}>{expanded ? '▼' : '▶'}</span>
        <span>Agent 调用了 {toolCallCount} 个工具</span>
      </div>

      {/* 展开状态：步骤详情 */}
      {expanded && (
        <div style={{ padding: '0 12px 8px', borderTop: '1px solid #e2e8f0' }}>
          {steps.map((step, i) => (
            <div key={i} style={{ marginTop: 6 }}>
              {step.type === 'tool_call' && (
                <div>
                  <span style={{ color: step.tool_name === 'web_search' ? '#d97706' : '#7c3aed', fontWeight: 600, fontSize: 12 }}>
                    {step.tool_name === 'web_search' ? ' ' : '⚙'} {step.tool_name}
                  </span>
                  <code style={{
                    display: 'block', marginTop: 2, padding: '4px 8px',
                    background: '#f1f5f9', borderRadius: 4, fontSize: 11,
                    whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                    maxHeight: 80, overflow: 'auto',
                  }}>
                    {JSON.stringify(step.tool_input, null, 2)}
                  </code>
                </div>
              )}
              {step.type === 'tool_result' && (
                <div style={{
                  paddingLeft: 12, borderLeft: '2px solid #e2e8f0',
                  color: '#475569', fontSize: 11, maxHeight: 60, overflow: 'auto',
                }}>
                  → {step.content?.slice(0, 300)}
                  {step.content?.length > 300 ? '...' : ''}
                </div>
              )}
              {step.type === 'final_answer' && (
                <div style={{ color: '#16a34a', fontWeight: 600, fontSize: 11 }}>
                  ✓ 生成最终回答
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageItem({ message, onSaveToKB }) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isFromKB = message.is_from_kb !== false;
  const hasWebSources = message.web_sources && message.web_sources.length > 0;
  const canSaveToKB = isAssistant && (!isFromKB || hasWebSources);

  return (
    <div style={{
      display: 'flex',
      width: '100%',
      marginBottom: 12,
      justifyContent: isUser ? 'flex-end' : 'flex-start',
    }}>
      <div style={{ maxWidth: '85%' }}>
        {/* Agent 推理步骤 */}
        {isAssistant && message.agent_steps && message.agent_steps.length > 0 && (
          <AgentSteps steps={message.agent_steps} />
        )}
        {/* Source indicator for assistant messages */}
        {isAssistant && (
          <div style={{
            fontSize: 11, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
          }}>
            {isFromKB ? (
              <span style={{ color: '#16a34a', fontWeight: 600 }}>
                <span style={{ marginRight: 4 }}>●</span>知识库
              </span>
            ) : (
              <span style={{ color: '#d97706', fontWeight: 600 }}>
                <span style={{ marginRight: 4 }}>●</span>AI搜索
              </span>
            )}
            {message.source_node_ids && message.source_node_ids.length > 0 && (
              <span style={{ color: '#94a3b8' }}>
                {message.source_node_ids.map(id => <SourceBadge key={id} nodeId={id} />)}
              </span>
            )}
            {message.web_sources && message.web_sources.length > 0 && (
              <span>
                {message.web_sources.map((ws, i) => (
                  <WebSourceBadge key={i} title={ws.title} url={ws.url} />
                ))}
              </span>
            )}
          </div>
        )}
        <div style={{
          borderRadius: 16,
          padding: '10px 16px',
          background: isUser ? '#2563eb' : '#ffffff',
          color: isUser ? '#fff' : '#1e293b',
          borderBottomRightRadius: isUser ? 4 : 16,
          borderBottomLeftRadius: isUser ? 16 : 4,
          border: isUser ? 'none' : '1px solid #e2e8f0',
          boxShadow: isUser ? 'none' : '0 1px 3px rgba(0,0,0,0.1)',
          fontSize: 14,
          lineHeight: 1.6,
        }}>
          <SimpleMarkdown text={message.content} />
        </div>
        {/* "添加到知识库" button for AI search / web search responses */}
        {canSaveToKB && (
          <div style={{ marginTop: 6 }}>
            <button
              onClick={() => onSaveToKB && onSaveToKB(message)}
              style={{
                padding: '5px 14px', fontSize: 12, fontWeight: 600,
                background: '#ecfdf5', color: '#065f46', border: '1px solid #a7f3d0',
                borderRadius: 8, cursor: 'pointer',
              }}
            >
              + 添加到知识库
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPanel() {
  const { showChatPanel, toggleChatPanel, activeConversationId, setActiveConversationId } = useAppStore();

  const [conversations, setConversations] = useState([]);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [error, setError] = useState(null);

  // API Key settings
  const [showSettings, setShowSettings] = useState(false);
  const [hasApiKey, setHasApiKey] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com/v1');
  const [modelName, setModelName] = useState('deepseek-chat');
  const [savingKey, setSavingKey] = useState(false);
  const [modelDisplay, setModelDisplay] = useState('');
  const [configSource, setConfigSource] = useState('unknown');

  // Save to KB dialog
  const [saveDialog, setSaveDialog] = useState(null);
  const [saveTitle, setSaveTitle] = useState('');
  const [savingKB, setSavingKB] = useState(false);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (showChatPanel) {
      loadConversations();
      api.getSettings().then(s => {
        setHasApiKey(s.has_api_key);
        setBaseUrl(s.ai_base_url);
        setModelName(s.ai_model_name);
        setModelDisplay(s.model || '');
        setConfigSource(s.source || 'unknown');
        if (!s.has_api_key) setShowSettings(true);
      }).catch(() => {});
    }
  }, [showChatPanel]);

  useEffect(() => {
    if (activeConversationId) {
      loadMessages(activeConversationId);
    } else {
      setMessages([]);
    }
  }, [activeConversationId]);

  const handleSaveKey = async () => {
    const keyToSave = apiKey.trim() || (hasApiKey ? null : '');
    if (!keyToSave && !hasApiKey) return;

    let fixedUrl = baseUrl.trim();
    if (fixedUrl && !fixedUrl.endsWith('/v1')) {
      fixedUrl = fixedUrl.replace(/\/+$/, '') + '/v1';
    }

    setSavingKey(true);
    try {
      const payload = { ai_base_url: fixedUrl, ai_model_name: modelName };
      if (keyToSave) payload.ai_api_key = keyToSave;
      await api.saveSettings(payload);
      setHasApiKey(true);
      setBaseUrl(fixedUrl);
      setShowSettings(false);
      setApiKey('');
      setError(null);
    } catch (e) {
      setError('保存失败: ' + e.message);
    }
    setSavingKey(false);
  };

  const loadConversations = async () => {
    try {
      const data = await api.getConversations();
      setConversations(data);
      if (data.length > 0 && !activeConversationId) {
        setActiveConversationId(data[0].id);
      }
    } catch (error) {
      console.error("Failed to load conversations:", error);
    }
  };

  const loadMessages = async (id) => {
    try {
      setLoading(true);
      const data = await api.getConversation(id);
      setMessages(data.messages || []);
    } catch (error) {
      console.error("Failed to load messages:", error);
    } finally {
      setLoading(false);
    }
  };

  const scrollToBottom = () => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  const handleNewChat = async () => {
    try {
      const conv = await api.createConversation({ title: "New Conversation" });
      setConversations([conv, ...conversations]);
      setActiveConversationId(conv.id);
    } catch (error) {
      console.error("Failed to create conversation:", error);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || loading) return;

    let convId = activeConversationId;
    if (!convId) {
      const conv = await api.createConversation({ title: "New Conversation" });
      setConversations([conv, ...conversations]);
      convId = conv.id;
      setActiveConversationId(convId);
    }

    const newMessage = { id: Date.now(), role: 'user', content: inputValue };
    setMessages(prev => [...prev, newMessage]);
    setInputValue('');
    setLoading(true);
    setError(null);
    scrollToBottom();

    try {
      const response = await api.sendMessage(convId, inputValue);
      setMessages(prev => [...prev, response]);
      if (messages.length === 0) loadConversations();
      scrollToBottom();
    } catch (error) {
      setError('发送失败: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveToKB = (message) => {
    const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
    setSaveDialog({
      question: lastUserMsg?.content || '',
      content: message.content,
    });
    setSaveTitle(lastUserMsg?.content?.slice(0, 50) || '');
  };

  const handleConfirmSave = async () => {
    if (!saveTitle.trim() || !saveDialog) return;
    setSavingKB(true);
    try {
      const result = await api.saveToKB({
        title: saveTitle.trim(),
        content: saveDialog.content,
        question: saveDialog.question,
      });
      setSaveDialog(null);
      setSaveTitle('');
      setError(null);
      const successMsg = { id: Date.now(), role: 'system', content: `已保存到知识库: ${result.title} (ID: ${result.node_id})` };
      setMessages(prev => [...prev, successMsg]);
      scrollToBottom();
    } catch (e) {
      setError('保存失败: ' + e.message);
    }
    setSavingKB(false);
  };

  if (!showChatPanel) return null;

  return (
    <div style={{
      position: 'absolute', right: 0, top: 0, bottom: 0, width: 400,
      background: '#f8fafc', borderLeft: '1px solid #e2e8f0',
      display: 'flex', flexDirection: 'column', zIndex: 30,
      boxShadow: '-4px 0 20px rgba(0,0,0,0.15)',
    }}>
      {/* Header */}
      <div style={{
        height: 50, borderBottom: '1px solid #e2e8f0', background: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={() => setShowSidebar(!showSidebar)} style={headerBtnStyle}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <span style={{ fontWeight: 600, fontSize: 15, color: '#1e293b' }}>AI Chat</span>
          {configSource === 'cc-switch' && modelDisplay && (
            <span style={{ fontSize: 11, color: '#16a34a', fontWeight: 500 }}>{modelDisplay}</span>
          )}
          {!hasApiKey && (
            <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>公共 Key</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={() => setShowSettings(!showSettings)} style={headerBtnStyle} title="API Settings">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
          <button onClick={toggleChatPanel} style={headerBtnStyle}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div style={{
          padding: 16, background: '#fffbeb', borderBottom: '1px solid #fde68a',
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: '#92400e' }}>API 设置</div>
          <div style={{ marginBottom: 8 }}>
            <label style={labelStyle}>API Key</label>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder="sk-xxxxxxxx" style={inputStyle} />
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={labelStyle}>Base URL</label>
            <input type="text" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
              style={inputStyle} />
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
              DeepSeek: https://api.deepseek.com/v1 | Kimi: https://api.moonshot.cn/v1
            </div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>Model</label>
            <input type="text" value={modelName} onChange={e => setModelName(e.target.value)}
              placeholder="deepseek-chat" style={inputStyle} />
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
              常用: deepseek-chat, moonshot-v1-8k, glm-4, qwen-turbo
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleSaveKey} disabled={savingKey || (!apiKey.trim() && !hasApiKey)} style={{
              padding: '8px 20px', background: '#2563eb', color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
              opacity: savingKey || (!apiKey.trim() && !hasApiKey) ? 0.5 : 1,
            }}>{savingKey ? 'saving...' : 'Save'}</button>
            <button onClick={() => setShowSettings(false)} style={{
              padding: '8px 16px', background: 'transparent', color: '#64748b',
              border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, cursor: 'pointer',
            }}>Cancel</button>
          </div>
          {hasApiKey && (
            <div style={{ marginTop: 8, fontSize: 12, color: '#16a34a' }}>已配置个人 API Key</div>
          )}
          {!hasApiKey && (
            <div style={{ marginTop: 8, fontSize: 12, color: '#94a3b8' }}>未配置时自动使用管理员的 Key</div>
          )}
        </div>
      )}

      {/* Save to KB dialog */}
      {saveDialog && (
        <div style={{
          padding: 16, background: '#ecfdf5', borderBottom: '1px solid #a7f3d0',
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: '#065f46' }}>保存到知识库</div>
          <div style={{ marginBottom: 8 }}>
            <label style={labelStyle}>笔记标题</label>
            <input type="text" value={saveTitle} onChange={e => setSaveTitle(e.target.value)}
              style={inputStyle} placeholder="输入标题..." />
          </div>
          <div style={{ marginBottom: 12, fontSize: 12, color: '#475569', maxHeight: 100, overflow: 'auto',
            padding: 8, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
            {saveDialog.content.slice(0, 300)}{saveDialog.content.length > 300 ? '...' : ''}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleConfirmSave} disabled={savingKB || !saveTitle.trim()} style={{
              padding: '8px 20px', background: '#059669', color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
              opacity: savingKB || !saveTitle.trim() ? 0.5 : 1,
            }}>{savingKB ? 'saving...' : '保存'}</button>
            <button onClick={() => { setSaveDialog(null); setSaveTitle(''); }} style={{
              padding: '8px 16px', background: 'transparent', color: '#64748b',
              border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, cursor: 'pointer',
            }}>Cancel</button>
          </div>
        </div>
      )}

      {/* Conversation sidebar */}
      {showSidebar && (
        <div style={{
          position: 'absolute', top: 50, left: 0, bottom: 0, width: 260,
          background: '#fff', borderRight: '1px solid #e2e8f0', zIndex: 10,
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: 12, borderBottom: '1px solid #e2e8f0' }}>
            <button onClick={() => { handleNewChat(); setShowSidebar(false); }} style={{
              width: '100%', padding: '8px 0', background: '#2563eb', color: '#fff',
              border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}>+ New Chat</button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
            {conversations.map(conv => (
              <button key={conv.id}
                onClick={() => { setActiveConversationId(conv.id); setShowSidebar(false); }}
                style={{
                  width: '100%', textAlign: 'left', padding: '8px 12px',
                  background: activeConversationId === conv.id ? '#eff6ff' : 'transparent',
                  color: activeConversationId === conv.id ? '#1d4ed8' : '#475569',
                  border: 'none', borderRadius: 8, fontSize: 13, cursor: 'pointer',
                  marginBottom: 2, display: 'block',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}
              >{conv.title}</button>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {messages.length === 0 && !loading && (
          <div style={{
            height: '100%', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', color: '#94a3b8',
          }}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <p style={{ fontSize: 14, marginTop: 12 }}>Ask anything about your knowledge base</p>
            <p style={{ fontSize: 12, marginTop: 4, color: '#cbd5e1' }}>需要配置 AI_API_KEY 才能使用</p>
          </div>
        )}
        {messages.map(msg => (
          msg.role === 'system' ? (
            <div key={msg.id} style={{
              textAlign: 'center', margin: '8px 0', fontSize: 12, color: '#16a34a',
              background: '#ecfdf5', padding: '6px 12px', borderRadius: 8,
              border: '1px solid #a7f3d0',
            }}>{msg.content}</div>
          ) : (
            <MessageItem
              key={msg.id}
              message={msg}
              onSaveToKB={handleSaveToKB}
            />
          )
        ))}
        {loading && (
          <div style={{ display: 'flex', marginBottom: 12 }}>
            <div style={{
              background: '#fff', border: '1px solid #e2e8f0', borderRadius: 16,
              borderBottomLeftRadius: 4, padding: '10px 16px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            }}>
              <span style={{ color: '#94a3b8', fontSize: 13 }}>Agent is working...</span>
            </div>
          </div>
        )}
        {error && (
          <div style={{
            padding: 12, background: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: 8, color: '#dc2626', fontSize: 13, marginBottom: 12,
          }}>{error}</div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ padding: 16, background: '#fff', borderTop: '1px solid #e2e8f0' }}>
        <form onSubmit={handleSubmit} style={{ position: 'relative' }}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Ask about your notes..."
            disabled={loading}
            style={{
              width: '100%', padding: '10px 44px 10px 16px', borderRadius: 20,
              border: '1px solid #e2e8f0', background: '#f1f5f9', fontSize: 14,
              outline: 'none', boxSizing: 'border-box',
            }}
          />
          <button type="submit" disabled={!inputValue.trim() || loading} style={{
            position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
            width: 36, height: 36, borderRadius: '50%', border: 'none',
            background: inputValue.trim() && !loading ? '#2563eb' : '#e2e8f0',
            color: inputValue.trim() && !loading ? '#fff' : '#94a3b8',
            cursor: inputValue.trim() && !loading ? 'pointer' : 'default',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </form>
        <div style={{ textAlign: 'center', marginTop: 6, fontSize: 11, color: '#cbd5e1' }}>
          AI responses may be inaccurate. Check sources.
        </div>
      </div>
    </div>
  );
}

const headerBtnStyle = {
  background: 'none', border: 'none', padding: 6, cursor: 'pointer',
  color: '#64748b', borderRadius: 6, display: 'flex', alignItems: 'center',
};

const labelStyle = {
  display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4,
};

const inputStyle = {
  width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e2e8f0',
  fontSize: 13, outline: 'none', boxSizing: 'border-box', background: '#fff',
};
