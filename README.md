# Knowledge Base

[![CI](https://github.com/happiness-cheng/knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/happiness-cheng/knowledge-base/actions/workflows/ci.yml)

[简体中文](./README_zh.md) &nbsp;&nbsp;|&nbsp;&nbsp; **English**

---

Personal knowledge management system: graph visualization + **benchmark-driven RAG chat** + intelligent note linking.

**In one line**: build a 28-query three-tier evaluation set first, measure the real retrieval floor, *then* optimize — every number is reproducible.

> [!WARNING]
> Personal learning project, not a production deployment. It binds to `127.0.0.1` by default — do not expose it to the public internet.

## 30-Second Overview

| Concern | How this project handles it |
|---|---|
| **The single most valuable thing** | **Measure before optimizing.** A 28-query three-tier eval set showed Recall@3 was only **10.7%** — turning "feels usable" into a reproducible number. After the fix: **92.9%** |
| **Full RAG pipeline** | Chunking → embedding → vector store → retrieval → generation → **clickable source citations**, all hand-rolled |
| **Failure triage** | Self-retrieval control experiment rules out index faults; then layered attribution (index / chunking / retrieval / generation) |
| **Chunking** | Semantic split by headings + **480-token cap** + CJK/Latin punctuation-aware splitting + code-block protection + hard-split fallback + **parent-child chunking** (match a small chunk, return the full parent) |
| **Query side** | Adds the bge **query instruction prefix** (query only, never documents) — the classic root cause of "eval looks great, production finds nothing" |
| **Agent** | ReAct loop + autonomous multi-tool selection + **loop detection** + graceful degradation to plain chat |
| **Multi-tenancy** | **Per-user ChromaDB collections**; tools only ever reach the authenticated user's data |
| **How it's proven** | **135 pytest green**; evaluation scripts are committed, so every change has a numeric guardrail |

## RAG Retrieval Quality (Data-Driven Optimization)

All numbers are reproducible — see `backend/eval/`:

| Metric | Before (MiniLM) | After (bge-large-zh-v1.5 + query instruction) |
|--------|----------------|-----------------------------------------------|
| **Recall@3** | 10.7% | **92.9%** |
| **MRR** | 0.136 | **0.818** |

**Optimization process** (single-variable controlled, per-case failure attribution):

1. **Evaluation first** — 28 queries × 3-tier corpus (short notes / long docs / external), with layered reports so a good total can't hide a weak tier.
2. **Root cause** — self-retrieval control experiments ruled out "the document never entered the index"; the real cause was an English-only model (MiniLM) failing on a Chinese corpus.
3. **Model switch** — `bge-large-zh-v1.5`, with full re-embedding, vector-DB backup, and 135 tests green.
4. **Chunking** — semantic split by headings + size fallback + title-prefixed encoding.
5. **Component testing** — hybrid search (BM25+RRF) and cross-encoder rerank show **no gain** at this recall level. Components are adopted based on observed failure modes, not by default.
6. **Failure attribution** — remaining failures traced to ambiguous queries (legitimate multi-topic competition). A Query Rewrite **offline experiment** moved the target document from rank 6 to rank 1 (**not shipped to production**).

### Deep-tail measurement

An eval set covering only "answers within the first 512 tokens" systematically overstates quality. After building queries that specifically target **deep tails with distinctive vocabulary**:

| Metric | Before | After |
|---|---|---|
| Deep-tail Recall | 5/7 = 71.4% | **7/7 = 100%** |
| Deepest note's tail content | `rank 203` | **`rank 1`** |
| Another tail case | `rank 7` | **`rank 1`** |

> The point: **your eval-set sampling decides which failures you are able to see.**

## Known Limitations

Disclosed on purpose — this is the honest state of the code today:

1. **`92.9%` has hard boundaries and is not the production number.** Three reasons: (a) all 28 queries have their answers **within the first 512 tokens**; (b) the eval applies the bge query instruction while production `rag_service.py` previously did not (now fixed); (c) part of the eval corpus comes from an **old SQLite database, not the production MySQL one**. Deep-tail behaviour has been measured separately, but the overall figure still needs a larger evaluation set.
2. **Query Rewrite is an offline experiment — production has zero implementation.** The production path is a direct vector search with no rewriting step.
3. **`run_kb_eval.py` uses brute-force cosine (`embs @ q`), not ChromaDB's ANN index** — so `92.9%` is an **exact-search** number, not a production approximate-search (HNSW) number.
4. **The evaluation script computes only Recall@3 and MRR — no NDCG.** Both blind spots matter with multiple gold documents: Recall@3 is binary and discards position; MRR only credits the first hit.
5. **Legacy embedding-cap debt**: `bge-large-zh-v1.5` caps at 512 tokens, so chunks produced before the token cap was added were silently truncated (no warning). The chunking layer now caps tokens and has regression tests, but **already-indexed vectors require re-embedding** for the fix to take effect.
6. **One SQLAlchemy warning remains** at `nodes.py:56`: `SAWarning: Coercing Subquery object into a select() for use in IN()`. Functionally fine today, but a future SQLAlchemy release may turn it into an error.
7. **Local tests are sensitive to the host proxy environment.** httpx defaults to `trust_env=True`; if `NO_PROXY` contains an *already-bracketed* IPv6 address (e.g. `[::1]`), httpx builds a malformed pattern `all://*[::1]` and raises `InvalidURL`, which breaks test collection. This is a local-environment issue; Linux CI is unaffected.
8. **`passlib` is unmaintained and incompatible with `bcrypt >= 4.1`.** On first `hash()`, passlib 1.7.4 (no release since 2020) runs a wraparound-bug self-test whose input exceeds 72 bytes; bcrypt ≥ 4.1 no longer truncates silently and raises `ValueError` instead. `requirements.txt` therefore constrains bcrypt to `>=4.0,<4.1`. **The proper long-term fix is to drop passlib and call `bcrypt.hashpw` / `checkpw` directly** (~10 lines; the bcrypt hash format is unchanged, so existing user passwords keep working) — not done yet.
9. **The CI branch filter was misconfigured.** The workflow only listened on `push: branches: [main]`, while the actual working branch is `master`, so **CI had never been triggered** (now fixed to `[master, main]`, and the default branch was switched to `master`). `main` is a stale 2026-05 branch with **no common ancestor** with `master`; it has not been merged or deleted yet.

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

## Agent Reliability

- ReAct loop with autonomous multi-tool selection; **every tool call is scoped to the authenticated user's knowledge base** (per-user vector collections).
- **Loop detection**: repeated identical tool calls across consecutive turns are treated as non-convergence and force a wrap-up; a hard `MAX_ITERATIONS` cap backs it up.
- **Degradation path**: if the first tool call fails, the Agent degrades to plain chat rather than stalling the user.
- Tool parameters are bounded; **knowledge-base and web content are both treated as untrusted data**.
- **Only nodes actually returned by Agent tools can be emitted as citations**.
- User-supplied provider keys are **encrypted at rest**; production startup requires explicit signing and encryption keys.

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.x, Alembic
- **Database**: MySQL (production, `pymysql`) / SQLite (lightweight)
- **Frontend**: React, Vite, Zustand
- **AI**: Anthropic Messages API (`base_url` / `model` configurable)
- **Vector search**: ChromaDB + sentence-transformers (`bge-large-zh-v1.5`)
- **Also**: `slowapi` rate limiting, `jieba` tokenization, `ddgs` web search, `python-jose` + `passlib` auth

## Quick Start

```bash
git clone https://github.com/happiness-cheng/knowledge-base.git
cd knowledge-base/backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Configure (see ENVIRONMENT.md) — create backend/.env with at least:
#   DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/knowledge_base?charset=utf8mb4
#   AI_API_KEY=...
#   AI_BASE_URL=https://your-anthropic-compatible-endpoint
#   AI_MODEL_NAME=...
venv\Scripts\python -m alembic upgrade head

cd ../frontend && npm install
cd .. && start.bat
```

See [README_zh.md](./README_zh.md) for the full documentation.

## Verification

```bash
cd backend && python -m pytest tests -q --tb=short   # 135 passed
cd ../frontend && npm run build
```

## License

[MIT](./LICENSE)
