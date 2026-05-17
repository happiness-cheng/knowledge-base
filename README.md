# Knowledge Base

AI-powered personal knowledge management system with graph visualization, RAG chat, and intelligent note linking.

## Features

- **Knowledge Graph** — Interactive force-directed graph visualization of your notes and their relationships
- **AI Analysis** — Automatic extraction of summaries, categories, tags, and importance from note content
- **RAG Chat** — Chat with your knowledge base using Retrieval-Augmented Generation (vector search + LLM)
- **Sub-topic Extraction** — Auto-extract `##` headings as graph sub-nodes with cross-note linking
- **Markdown Support** — Write notes in Markdown with live preview
- **File Import** — Import `.md`, `.txt`, `.docx` files (single or batch)
- **Tag System** — Organize notes with colorful tags, filter by tag
- **Topic-level Relationships** — Link specific sub-topics across different notes

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, SQLAlchemy, SQLite |
| Frontend | React, Vite |
| AI | DeepSeek/OpenAI-compatible API |
| Vector DB | ChromaDB + sentence-transformers |
| Chat DB | SQLite with conversation history |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/happiness-cheng/knowledge-base.git
cd knowledge-base

# 2. Set up backend
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 3. Configure API key (see ENVIRONMENT.md)
cp .env.example .env  # then edit with your API key

# 4. Start (Windows)
# Double-click start.bat, or:
cd ..
start.bat
```

The app opens at **http://localhost:5173**

## Project Structure

```
knowledge-base/
├── backend/
│   ├── app/
│   │   ├── routers/     # API endpoints
│   │   ├── models/      # SQLAlchemy models
│   │   ├── schemas/     # Pydantic schemas
│   │   ├── services/    # Business logic (AI, RAG, file import)
│   │   └── utils/       # Helpers (markdown cleaning)
│   └── tests/           # pytest test suite (114 tests)
├── frontend/
│   └── src/
│       ├── components/  # React components
│       ├── stores/      # Zustand state management
│       └── api/         # API client
├── start.bat            # One-click startup
└── ENVIRONMENT.md       # Environment setup guide
```

## Testing

```bash
cd backend
venv/Scripts/python.exe -m pytest tests/ -v
```

114 backend tests covering CRUD, relationships, tags, graph, sub-topic extraction, import, and chat.

## License

MIT
