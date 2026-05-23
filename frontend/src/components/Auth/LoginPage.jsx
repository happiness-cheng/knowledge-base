import { useState } from 'react'
import { api } from '../../api/client'
import { auth } from '../../api/auth'

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) return
    setLoading(true)
    setError('')
    try {
      const fn = isRegister ? api.register : api.login
      const data = await fn(username.trim(), password)
      auth.setToken(data.access_token)
      window.location.reload()
    } catch (err) {
      setError(err.message || '请求失败')
    }
    setLoading(false)
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)', fontFamily: 'system-ui, -apple-system, sans-serif',
    }}>
      <div style={{
        width: 380, padding: 40, background: '#1e293b', borderRadius: 16,
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', border: '1px solid #334155',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>
            Knowledge Base
          </div>
          <div style={{ fontSize: 14, color: '#94a3b8' }}>
            {isRegister ? '创建账号' : '登录你的账号'}
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#cbd5e1', marginBottom: 6 }}>
              用户名
            </label>
            <input
              type="text" value={username} onChange={e => setUsername(e.target.value)}
              placeholder="输入用户名" autoFocus
              style={{
                width: '100%', padding: '10px 14px', borderRadius: 8,
                border: '1px solid #475569', background: '#0f172a', color: '#f1f5f9',
                fontSize: 14, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: 24 }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#cbd5e1', marginBottom: 6 }}>
              密码
            </label>
            <input
              type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="输入密码"
              style={{
                width: '100%', padding: '10px 14px', borderRadius: 8,
                border: '1px solid #475569', background: '#0f172a', color: '#f1f5f9',
                fontSize: 14, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          {error && (
            <div style={{
              padding: '8px 12px', marginBottom: 16, background: '#450a0a', border: '1px solid #7f1d1d',
              borderRadius: 8, color: '#fca5a5', fontSize: 13,
            }}>
              {error}
            </div>
          )}

          <button type="submit" disabled={loading || !username.trim() || !password.trim()} style={{
            width: '100%', padding: '12px 0', borderRadius: 8, border: 'none',
            background: loading ? '#475569' : '#2563eb', color: '#fff',
            fontSize: 15, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
          }}>
            {loading ? '处理中...' : (isRegister ? '注册' : '登录')}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 20 }}>
          <button onClick={() => { setIsRegister(!isRegister); setError('') }} style={{
            background: 'none', border: 'none', color: '#60a5fa', fontSize: 13,
            cursor: 'pointer', textDecoration: 'underline',
          }}>
            {isRegister ? '已有账号？登录' : '没有账号？注册'}
          </button>
        </div>
      </div>
    </div>
  )
}
