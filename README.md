# Knowledge Base

[简体中文](./README_zh.md) &nbsp;&nbsp;|&nbsp;&nbsp; **English**

---

AI-powered personal knowledge management system with graph visualization, RAG chat, and intelligent note linking.

## Features

| Feature | Description |
|---------|-------------|
| **Knowledge Graph** | Interactive force-directed graph with drag, zoom, and relationship visualization |
| **AI Analysis** | Auto-extract summaries, categories, tags, and importance from notes |
| **RAG Chat** | Chat with your knowledge base using vector search + LLM, with source citations |
| **Sub-topic Extraction** | Auto-extract `##` headings as graph sub-nodes with cross-note linking |
| **Markdown Editor** | Side-by-side editing with live preview |
| **File Import** | Import `.md`, `.txt`, `.docx` files (single or batch) |
| **Tag System** | Colorful tags, tag filtering, tag cloud |
| **Topic-level Linking** | Link specific sub-topics across different notes (not just note-to-note) |

## Quick Start

```bash
git clone https://github.com/happiness-cheng/knowledge-base.git
cd knowledge-base
cd backend && python -m venv venv && venv\Scripts\pip install -r requirements.txt
cd ../frontend && npm install
cd .. && start.bat
```

See [README_zh.md](./README_zh.md) for detailed documentation.

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, SQLite
- **Frontend**: React, Vite, Zustand
- **AI**: DeepSeek/OpenAI-compatible API, ChromaDB vector search
- **Tests**: 114 pytest tests

## License

[MIT](./LICENSE)
