# Knowledge Base

[![CI](https://github.com/happiness-cheng/knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/happiness-cheng/knowledge-base/actions/workflows/ci.yml)

[简体中文](./README_zh.md) &nbsp;&nbsp;|&nbsp;&nbsp; **English**

---

AI-powered personal knowledge management system with graph visualization, RAG chat, and intelligent note linking.

## RAG Retrieval Quality (Data-Driven Optimization)

The retrieval pipeline is systematically benchmarked. All numbers are reproducible (see `backend/eval/`):

| Metric | Before (MiniLM) | After (bge-large-zh-v1.5 + query instruction) |
|--------|----------------|-----------------------------------------------|
| **Recall@3** | 10.7% | **92.9%** |
| **MRR** | 0.136 | **0.818** |

**Optimization process** (single-variable controlled, per-case failure attribution):

1. **Evaluation first**: 28 queries × 3-tier corpus (short notes / long docs / external), layered reports
2. **Root cause**: self-retrieval control experiments ruled out pipeline faults → English-only MiniLM fails on Chinese corpus
3. **Model switch**: bge-large-zh-v1.5 (+ full re-embedding, vector DB backup, 135 pytest green)
4. **Chunking**: semantic split by headings + size fallback + title-prefixed encoding
5. **Component testing**: hybrid search (BM25+RRF) and cross-encoder rerank show no gain at this recall level — components are adopted based on failure modes, not by default
6. **Failure attribution**: remaining 2 failures traced to ambiguous queries (legitimate multi-topic competition); Query Rewrite experiment moved target doc rank 6→1

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

## Agent reliability

- Every Agent tool call is scoped to the authenticated user's knowledge base.
- Tool parameters are bounded, and knowledge-base/web content is treated as untrusted data.
- Only nodes actually returned by Agent tools can be emitted as knowledge citations.
- User-supplied provider keys are encrypted at rest; production startup requires explicit signing and encryption keys.

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
- **Verification**: pytest backend suite and Vite production build

## Verification

```bash
cd backend && python -m pytest tests -q --tb=short
cd ../frontend && npm run build
```

## License

[MIT](./LICENSE)
