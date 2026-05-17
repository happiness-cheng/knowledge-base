# Knowledge Base 项目规范

## 自动测试

- 后端测试位于 `backend/tests/`，使用 pytest
- 运行命令：`cd backend && venv/Scripts/python.exe -m pytest tests/ -v`
- 后台自动测试脚本：`auto_test_start.bat`（每30分钟跑一次，持续到2026-06-07）
- 测试失败时会在项目根目录生成 `NEEDS_FIX.txt`
- **每次会话启动时必须检查 `NEEDS_FIX.txt` 是否存在**，存在则读取内容并修复

## 项目结构

- 后端：FastAPI + SQLAlchemy + SQLite，端口 8765/8766
- 前端：React (Vite)，端口 5173
- 数据库：`~/.knowledge_base/knowledge.db`
- AI：通过可配置的 API（默认 DeepSeek）实现知识提取、关系发现、对话

## API 路由

所有路由前缀 `/api`：
- `/api/nodes` — 知识节点 CRUD
- `/api/tags` — 标签 CRUD
- `/api/relationships` — 关系 CRUD
- `/api/graph` — 图谱数据
- `/api/import` — 文件/文本导入
- `/api/ai` — AI 分析、设置
- `/api/chat` — 对话管理、RAG 对话