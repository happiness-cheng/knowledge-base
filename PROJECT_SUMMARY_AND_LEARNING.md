# 知识库项目 — 全景总结 & AI/LLM 学习路线

## 一、项目全景

### 一句话

个人知识管理平台：写笔记 → AI 自动提取摘要/标签/关系 → 构建知识图谱 → 基于知识库的 RAG 智能问答。

### 技术栈

| 层 | 技术 | 作用 |
|----|------|------|
| 后端 | FastAPI + SQLAlchemy + SQLite | REST API，7 个路由模块 |
| 前端 | React 18 + Vite + Zustand | SPA，力导向图谱可视化 |
| 向量库 | ChromaDB + sentence-transformers | RAG 检索（all-MiniLM-L6-v2） |
| AI | Anthropic SDK（兼容 DeepSeek/MiMo 等代理） | 知识提取、关系发现、对话 |
| 中文分词 | jieba | 子知识点提取、关键词链接推荐 |
| 桌面化 | PyInstaller + tkinter | 打包为 exe |

### 架构图

```
用户写笔记 / 导入文件
        │
        ▼
   ┌─────────────┐    POST /api/nodes     ┌────────────────┐
   │  React 前端  │ ──────────────────────▶│  FastAPI 后端   │
   │  (Vite 5173) │                        │  (uvicorn 8766) │
   └──────┬───────┘                        └───────┬────────┘
          │                                        │
          │  ◀── 力导向图谱 SVG                     ├──▶ SQLite（知识节点/标签/关系）
          │  ◀── 详情抽屉                            ├──▶ ChromaDB（向量索引）
          │  ◀── Chat 面板                           └──▶ LLM API（知识提取/问答）
          │
   ┌──────▼───────┐
   │  Zustand     │  全局状态：nodes, tags, graph, relationships
   │  appStore.js │  UI 状态：selectedNode, showEditor, showChat...
   └──────────────┘
```

### 模块拆解（后端 7 个路由）

| 路由 | 文件 | 端点数 | 核心功能 |
|------|------|--------|---------|
| `/api/nodes` | `routers/nodes.py` | 7 | CRUD + 子知识点提取 + 推荐链接 |
| `/api/tags` | `routers/tags.py` | 3 | 标签 CRUD，LEFT JOIN 统计节点数 |
| `/api/relationships` | `routers/relationships.py` | 3 | 关系 CRUD |
| `/api/graph` | `routers/graph.py` | 2 | 全图数据 + BFS 子图查询 |
| `/api/import` | `routers/import_files.py` | 3 | .md/.txt/.docx 导入 + 文本粘贴 |
| `/api/ai` | `routers/ai.py` | 6 | AI 分析/设置/关系发现/批量分析 |
| `/api/chat` | `routers/chat.py` | 5 | 对话管理 + RAG 问答 + 存入知识库 |

### 数据库 ER 图

```
sources (1) ──▶ (N) knowledge_nodes (N) ──▶ (N) tags
                              │
                              │ (自引用，多对多)
                              ▼
                        relationships
                     (source_id → target_id)

conversations (1) ──▶ (N) messages (N) ──▶ (N) knowledge_nodes
                                          (via message_sources)
```

### AI 模块详解（你接下来要啃的核心）

| 模块 | 文件 | 做什么 | 用到的 AI 概念 |
|------|------|--------|---------------|
| AIClient | `claude_client.py` | 封装 Anthropic SDK，单轮/多轮对话 | API 调用、system prompt、response 解析 |
| 知识提取 | `knowledge_extractor.py` | 从笔记中提取结构化 JSON（摘要/分类/标签/重要度） | Prompt Engineering、结构化输出 |
| 关系发现 | `relationship_finder.py` | 发现节点之间的关系（类型+强度） | Prompt Engineering、批量推理 |
| RAG 对话 | `chat_service.py` | 检索知识库 → 构建上下文 → LLM 回答 → 回退策略 | RAG pipeline、context injection、fallback |
| 向量检索 | `rag_service.py` | ChromaDB + sentence-transformers 做语义搜索 | Embedding、向量数据库、语义相似度 |
| 自动链接 | `auto_linker.py` | jieba 分词 + Jaccard 相似度推荐关联节点 | NLP 分词、相似度算法（零 LLM 成本） |

---

## 二、你现在的位置

```
✅ 已掌握：后端开发（FastAPI/Python/SQLAlchemy/SQLite）
✅ 已掌握：前端基础（React/Vite/Zustand）
✅ 已掌握：C++ 高并发系统（event_collector + event_stream_engine）
⚠️ 会用但不懂原理：Claude API 调用（能跑通，不理解底层）
❌ 零基础：Transformer / Embedding / 向量数据库 / RAG / Prompt Engineering / Agent
```

---

## 三、AI/LLM 学习路线（6 周）

> 每周 5 天学理论 + 练代码，周六项目实战，周日复盘。
> 每个知识点都对应你知识库项目里的真实代码，学完就能改、改完就能讲。

### 第 1 周：LLM 基础 + Prompt Engineering

**目标**：理解大模型是怎么工作的，能写出高质量的 prompt

| 天 | 学什么 | 怎么练 | 对应项目代码 |
|----|--------|--------|-------------|
| 1-2 | Transformer 架构（self-attention、位置编码、KV cache） | 看图理解，不要求推公式 | 面试八股 |
| 3-4 | Token、Temperature、Top-P、Max Tokens | 改 `knowledge_extractor.py` 的 `max_tokens` 参数观察输出变化 | `claude_client.py:60-65` |
| 5-6 | Prompt Engineering（system prompt、few-shot、CoT） | 重写 `knowledge_extractor.py` 的 SYSTEM_PROMPT，对比提取质量 | `knowledge_extractor.py:5-17` |
| 7 | 结构化输出（JSON mode、输出格式约束） | 改 system prompt 让 LLM 输出稳定的 JSON，加 JSON Schema 校验 | `knowledge_extractor.py:8-14` + `relationship_finder.py` |

**具体练习**：
1. 打开 `knowledge_extractor.py`，看第 5-17 行的 SYSTEM_PROMPT
2. 尝试加 few-shot 示例（给 2-3 个输入→输出的例子）
3. 对比加 few-shot 前后提取结果的质量差异
4. 改 `temperature` 参数（在 `claude_client.py` 的 `messages.create` 调用里加）

**推荐资料**：
- Anthropic Prompt Engineering 指南：https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering
- OpenAI Prompt Engineering Guide：https://platform.openai.com/docs/guides/prompt-engineering
- 3Blue1Brown - Transformers 可视化：https://www.youtube.com/watch?v=wjZofJX0v4M
- Jay Alammar - The Illustrated Transformer：http://jalammar.github.io/illustrated-transformer/

**本周检查点**：
- [ ] 能解释 self-attention 的计算过程（Q、K、V 矩阵是什么）
- [ ] 能解释 temperature=0 vs temperature=1 的区别
- [ ] 能写出带 few-shot 示例的 system prompt
- [ ] 能让 LLM 稳定输出符合 JSON Schema 的结果

---

### 第 2 周：Embedding + 向量数据库

**目标**：理解"把文字变成数字"的原理，掌握向量检索

| 天 | 学什么 | 怎么练 | 对应项目代码 |
|----|--------|--------|-------------|
| 1-2 | Embedding 概念（词向量、句向量、语义空间） | 用 sentence-transformers 对几句话算 embedding，看余弦相似度 | `rag_service.py:29-33` |
| 3-4 | 向量数据库原理（ANN 检索、HNSW 算法） | 理解 ChromaDB 底层怎么做近似最近邻搜索 | `rag_service.py:12-14` |
| 5-6 | 文档分块策略（固定长度 vs 语义分块 vs 递归分块） | 改造 `file_importer.py`，实验不同 chunk size | `rag_service.py:35-46` + `file_importer.py` |
| 7 | Embedding 模型选型（all-MiniLM-L6-v2 vs BGE vs text-embedding-3） | 换不同模型，对比检索质量 | `rag_service.py:25` |

**具体练习**：
1. 写一个小脚本，用 `sentence-transformers` 对 10 句话算 embedding
2. 用余弦相似度找出最相似的两句话
3. 读 `rag_service.py` 的 `retrieve_relevant_nodes` 函数，理解 query → embedding → ChromaDB → results 的完整流程
4. 给 ChromaDB 传不同的 `top_k`，观察返回结果的变化

**推荐资料**：
- Pinecone 学习中心（Embedding 章节）：https://www.pinecone.io/learn/vector-embeddings/
- Chunking 策略综述：https://www.pinecone.io/learn/chunking-strategies/
- ChromaDB 官方文档：https://docs.trychroma.com/
- 向量数据库性能对比：https://benchmark.vectorview.ai/

**本周检查点**：
- [ ] 能解释 embedding 是什么、为什么能表示语义
- [ ] 能解释余弦相似度 vs 欧氏距离的区别和适用场景
- [ ] 能描述 ChromaDB 的 upsert/query/delete 流程
- [ ] 能说清楚为什么用 `all-MiniLM-L6-v2`（384 维、轻量、离线可用）

---

### 第 3 周：RAG（检索增强生成）

**目标**：掌握 RAG 的完整 pipeline，理解你的知识库问答是怎么工作的

| 天 | 学什么 | 怎么练 | 对应项目代码 |
|----|--------|--------|-------------|
| 1-2 | RAG 概念（为什么要 RAG、和 Fine-tuning 的区别） | 画出 RAG 的完整流程图 | — |
| 3-4 | RAG Pipeline 实现（chunk → embed → store → retrieve → generate） | 通读 `chat_service.py`，画出你的 RAG 流程 | `chat_service.py:30-93` |
| 5-6 | Context Injection（怎么把检索结果塞进 prompt） | 研究 `chat_service.py` 的 XML 格式 context 构建 | `chat_service.py:58-62` |
| 7 | RAG 评估 + 降级策略 | 分析 `chat_service.py` 的 NOT_FOUND_IN_KB 回退逻辑 | `chat_service.py:77-86` |

**具体练习**：
1. 手动走一遍 RAG 流程：
   - 创建 3 个知识节点
   - 触发 ChromaDB 索引（`add_node_to_index`）
   - 发一个 chat 请求，观察 `retrieve_relevant_nodes` 返回什么
   - 观察 system prompt 里 `<context>` 标签的内容
2. 研究回退策略：
   - 问一个知识库里没有的问题
   - 观察 `chat_service.py` 第 77-86 行的 NOT_FOUND_IN_KB 检测逻辑
   - 理解自动切换到 AI 通用知识的流程

**推荐资料**：
- LangChain RAG 教程（看流程）：https://python.langchain.com/docs/tutorials/rag/
- Anthropic 长上下文最佳实践：https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips
- RAG 评估方法：https://docs.ragas.io/en/stable/

**本周检查点**：
- [ ] 能从零画出 RAG 的 5 步流程图（Chunk → Embed → Store → Retrieve → Generate）
- [ ] 能解释你的项目里 `chat_service.py` 的 context injection 是怎么做的
- [ ] 能解释 NOT_FOUND_IN_KB 回退策略的设计思路
- [ ] 能回答面试题："RAG 和 Fine-tuning 怎么选？"

---

### 第 4 周：知识图谱 + 结构化知识

**目标**：理解知识图谱的建模方式，以及怎么和 LLM 结合

| 天 | 学什么 | 怎么练 | 对应项目代码 |
|----|--------|--------|-------------|
| 1-2 | 知识图谱基础（三元组、实体、关系、属性） | 分析你的数据库 ER 图，对照三元组模型 | `models/node.py` + `models/relationship.py` |
| 3-4 | 图数据库入门（Neo4j、Cypher 查询语言） | 装一个 Neo4j，把你的 SQLite 数据导过去跑查询 | 扩展练习 |
| 5-6 | GraphRAG（微软）：Local/Global 搜索 | 理解 GraphRAG 的两层检索机制 | 面试加分项 |
| 7 | 子知识点提取 + 自动链接 | 通读 `auto_linker.py`，理解 jieba + Jaccard | `auto_linker.py` + `routers/ai.py:185-234` |

**具体练习**：
1. 画出你的知识库的三元组：`(Node)-[RELATED_TO]->(Node)`，`(Node)-[HAS_TAG]->(Tag)`
2. 读 `auto_linker.py`，理解：
   - jieba 分词怎么把中文切成关键词
   - Jaccard 相似度怎么算（交集/并集）
   - 为什么标题权重 3 倍
3. 读 `routers/ai.py:185-234` 的 `extract_subtopics`，理解三级正则回退策略

**推荐资料**：
- Neo4j 入门教程：https://neo4j.com/developer/get-started/
- GraphRAG 论文：https://arxiv.org/abs/2404.16130
- 知识图谱与大模型结合综述：https://arxiv.org/abs/2310.07581
- Jaccard 相似度详解：https://en.wikipedia.org/wiki/Jaccard_index

**本周检查点**：
- [ ] 能解释三元组 (Subject, Predicate, Object) 是什么
- [ ] 能写基本的 Cypher 查询（MATCH、WHERE、RETURN）
- [ ] 能解释 GraphRAG 和传统 RAG 的区别
- [ ] 能说清楚 `auto_linker.py` 的关键词匹配流程

---

### 第 5 周：Agent 架构 + Tool Use

**目标**：理解什么是 Agent，怎么设计能自主决策的系统

| 天 | 学什么 | 怎么练 | 对应项目代码 |
|----|--------|--------|-------------|
| 1-2 | Agent 概念（LLM + 工具 + 循环） | 画出 Agent 的 Plan→Act→Observe 循环 | — |
| 3-4 | ReAct 模式（Reasoning + Acting） | 分析你的 chat_service 是否符合 ReAct | `chat_service.py` |
| 5-6 | Tool Use / Function Calling | 给 Claude 定义 tool schema，让它自己选择调用 API | 扩展知识库 |
| 7 | Multi-Agent（多 Agent 协作） | 理解 CrewAI/AutoGen 的设计思路 | 面试加分项 |

**具体练习**：
1. 分析你现有的 AI 调用算不算 Agent：
   - `knowledge_extractor.py`：单次调用，提取结构化数据 → 不算 Agent，是 Tool
   - `chat_service.py`：有 RAG 检索 + 回退逻辑 → 有 Agent 的雏形
   - 如果加一步"LLM 自己决定要不要检索、检索几次、要不要调用其他工具"→ 就是 Agent
2. 给知识库加一个 Tool Use：
   - 定义 tool schema：`search_kb(query)`、`create_note(title, content)`、`get_graph_stats()`
   - 让 LLM 自己决定调哪个工具
   - 实现一个简单的 Agent 循环

**推荐资料**：
- Lilian Weng - LLM Powered Autonomous Agents：https://lilianweng.github.io/posts/2023-06-23-agent/
- ReAct 论文：https://arxiv.org/abs/2210.03629
- Anthropic Tool Use 文档：https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- LangChain Agent 文档（看架构）：https://python.langchain.com/docs/concepts/agents

**本周检查点**：
- [ ] 能画出 Agent 的完整循环图
- [ ] 能解释 ReAct 和 Chain-of-Thought 的区别
- [ ] 能实现一个简单的 Tool Use（LLM 自己选工具调用）
- [ ] 能回答面试题："Agent 和普通 LLM 调用有什么区别？"

---

### 第 6 周：项目整合 + 面试准备

**目标**：把所有知识串起来，准备好面试话术

| 天 | 做什么 |
|----|--------|
| 1-2 | 给知识库加 Agent 能力：LLM 自动决定分析策略（哪些节点需要深度分析、哪些简单提取就行） |
| 3-4 | 写项目 README + 架构图 + 录 demo |
| 5-6 | 准备面试问答（见下方高频问题） |
| 7 | 模拟面试 |

---

## 四、面试高频问题（AI/LLM 部分）

| 问题 | 你的回答要点 | 对应代码 |
|------|-------------|---------|
| RAG 的完整流程是什么？ | 5 步：文档分块 → Embedding → 向量存储 → 检索 Top-K → 将结果注入 Prompt 交给 LLM 生成 | `rag_service.py` + `chat_service.py` |
| 你的 RAG 有回退策略吗？ | 有。LLM 回复含 NOT_FOUND_IN_KB 时自动切换到 AI 通用知识回答，用户也可手动选 AI 搜索模式 | `chat_service.py:77-86` |
| Embedding 模型怎么选？ | 看场景。我的项目用 all-MiniLM-L6-v2（384 维、轻量可离线），中文场景可换 BGE-M3 | `rag_service.py:25` |
| Prompt Engineering 有什么技巧？ | System prompt 分角色、few-shot 给示例、结构化输出约束（JSON Schema）、CoT 分步推理 | `knowledge_extractor.py` |
| 知识图谱和 RAG 怎么结合？ | 图谱存结构化关系（三元组），RAG 存非结构化文档。GraphRAG 先从图谱提取社区摘要，再做全局检索 | `models/relationship.py` + `auto_linker.py` |
| Agent 和普通调用区别？ | 普通调用=单次问答；Agent=自主决策循环（Plan→Act→Observe），能调工具、有记忆 | — |
| 怎么处理 LLM 的 hallucination？ | 限制输出格式（JSON）+ 引用数据源 + 温度调低 + 结构化校验 + 二次验证 | `knowledge_extractor.py:39` |
| 向量数据库怎么选？ | 本项目 ChromaDB（轻量嵌入式），生产可选 Milvus/Qdrant/Weaviate（分布式） | `rag_service.py:12` |
| Chunk size 怎么定？ | 看文档类型。笔记类 300-500 token，技术文档按段落分，代码按函数分。实验不同大小对比召回率 | `rag_service.py` |
| Fine-tuning 和 RAG 怎么选？ | RAG：知识密集型（事实查询、频繁更新）；Fine-tuning：风格/格式调整、领域术语 | — |

---

## 五、你的项目代码速查表

学每个知识点时，按这个表找到对应代码：

| 学什么 | 去看哪个文件 | 关键函数/行 |
|--------|-------------|------------|
| LLM API 调用 | `backend/app/services/claude_client.py` | `AIClient.chat()` 第 56-75 行 |
| Prompt 设计 | `backend/app/services/knowledge_extractor.py` | `SYSTEM_PROMPT` 第 5-17 行 |
| 结构化输出解析 | `backend/app/services/knowledge_extractor.py` | `extract_knowledge()` 第 20-47 行 |
| Embedding 生成 | `backend/app/services/rag_service.py` | `get_embedding()` 第 29-33 行 |
| 向量存储 | `backend/app/services/rag_service.py` | `add_node_to_index()` 第 35-46 行 |
| 向量检索 | `backend/app/services/rag_service.py` | `retrieve_relevant_nodes()` 第 56-80 行 |
| RAG pipeline | `backend/app/services/chat_service.py` | `generate_chat_response()` 第 30-93 行 |
| Context injection | `backend/app/services/chat_service.py` | 第 58-62 行（XML 格式构建） |
| 回退策略 | `backend/app/services/chat_service.py` | 第 77-86 行（NOT_FOUND_IN_KB 检测） |
| 关系发现 prompt | `backend/app/services/relationship_finder.py` | 整个文件 |
| 中文分词 + 相似度 | `backend/app/services/auto_linker.py` | 整个文件 |
| 子知识点提取 | `backend/app/routers/ai.py` | `extract_subtopics()` 第 185-234 行 |
| 前端图谱渲染 | `frontend/src/components/Graph/KnowledgeGraph.jsx` | 力导向布局算法 |
| 前端状态管理 | `frontend/src/stores/appStore.js` | Zustand store |

---

## 六、每周时间分配

| 时段 | 做什么 |
|------|--------|
| 周一-周五 每天 1-2 小时 | 学理论 + 读代码 + 写练习 |
| 周六 3-4 小时 | 项目实战（改代码、跑实验、对比效果） |
| 周日 2 小时 | 复盘 + 写知识笔记 + 更新简历 |

---

## 七、学完后的简历竞争力

| 技能 | 你的项目能证明 |
|------|---------------|
| RAG | ✅ 完整 pipeline：ChromaDB + sentence-transformers + context injection + 回退策略 |
| Prompt Engineering | ✅ 结构化输出、few-shot、system prompt 设计 |
| 向量数据库 | ✅ ChromaDB 实战，embedding + 索引 + 检索 |
| 知识图谱 | ✅ 实体关系模型 + 自动链接 + 子知识点提取 |
| Agent（加分） | ✅ Tool Use 扩展 + ReAct 分析 |
| 全栈工程 | ✅ 后端/前端/测试/桌面化/CI |
