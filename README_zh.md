# Knowledge Base

**简体中文** | [English](./README.md)

> 个人知识管理系统：知识图谱可视化 + **评测驱动的 RAG 智能问答** + 笔记智能关联。

**一句话**：先用 28 条三层评测集量出检索水位，再动手优化；每一个数字都可复现。

> [!WARNING]
> 个人学习项目，非生产部署。默认只绑定本机 `127.0.0.1`，请勿直接暴露到公网。

---

## 30 秒速览（给面试官）

| 关注点 | 本项目怎么做 |
|---|---|
| **最有价值的一件事** | **先量化再优化**。动手前先建 28 条三层评测集，测出 Recall@3 只有 **10.7%**，把"感觉能用"变成可复现的数字；优化后到 **92.9%** |
| **RAG 全链路** | 文档切分 → 嵌入 → 向量库 → 检索 → 生成 → **引用溯源可跳转**，全链路自己实现 |
| **检索失败怎么排查** | 用**自检索对照**排除索引故障，再逐层归因（索引 / 切分 / 检索 / 生成四层） |
| **切分策略** | 语义切分（按标题）+ **token 封顶 480** + 中英标点断句 + 代码块保护 + 无标点硬切兜底 + **父子切割**（命中小块、返回大块） |
| **查询侧** | 补齐 bge 官方**查询指令前缀**（query 加、文档不加）——这是"评测好看但线上搜不到"的经典根因 |
| **Agent 能力** | ReAct 循环 + 多工具自主选择 + **死循环检测** + 工具失败降级为普通聊天 |
| **多租户** | **每用户独立 ChromaDB 集合**，工具只访问当前认证用户的知识库 |
| **怎么证明它是对的** | **135 项 pytest 全绿**；评测脚本落盘可复现，每次改动有数字护栏 |

---

## RAG 检索质量（数据驱动优化）

检索链路经过系统化评测与优化，**全部数字可复现**（评测脚本见 `backend/eval/`）：

| 指标 | 优化前（MiniLM） | 优化后（bge-large-zh-v1.5 + 查询前缀） |
|------|----------------|--------------------------------------|
| **Recall@3** | 10.7% | **92.9%** |
| **MRR** | 0.136 | **0.818** |

**优化过程**（每步单变量对照，失败 case 逐条归因）：

1. **评测集先行**：28 条查询 × 三层语料（本地短笔记 / 项目长文档 / 外部开源语料），**分层报告**避免总分掩盖薄弱环节。
2. **根因定位**：自检索对照实验排除"文档没进索引"，确认根因是**英文模型（MiniLM）处理中文语料语义失效**。
3. **模型换型**：切换 `bge-large-zh-v1.5`（+ 全量重嵌入、向量库备份、135 项回归全绿）。
4. **切片策略**：语义切分（按标题）+ size 兜底（超长小节按句二次切）+ 标题拼接编码（语义锚点进向量）。
5. **组件实测**：混合检索（BM25+RRF）与 Cross-Encoder 精排在当前水位**均无增益**——组件引入以失败模式为依据，不堆砌。
6. **失败归因**：剩余失败 case 定位为查询歧义（多主题文档合法竞争），Query Rewrite **离线实验**将目标文档排名 6→1（**尚未上生产**）。

### 深尾内容专项测量

评测集若只覆盖"答案在文档前 512 token"的样本，会系统性高估效果。针对**深尾部 + 独特词汇**单独构造查询后：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 深尾 query Recall | 5/7 = 71.4% | **7/7 = 100%** |
| 最长笔记的尾部内容排名 | `rank 203` | **`rank 1`** |
| 另一条尾部内容排名 | `rank 7` | **`rank 1`** |

> 这条数据的意义：**评测集选样决定你能看见什么失败。** 只测头部 = 看不见截断问题。

---

## 已知限制（主动交底）

这些都是当前代码的**真实状态**：

1. **`92.9%` 有明确边界，不等于线上真实水位。** 三个原因：① 28 条 query 的答案**都在文档前 512 token 内**（未覆盖深尾）② 评测使用 bge 官方查询前缀，而生产 `rag_service.py` **此前未加前缀**（已修）③ 评测语料部分来自**旧 SQLite 库，不是生产 MySQL 库**。深尾问题已单独测量（见上），但**整体水位仍需更大规模评测集标定**。
2. **Query Rewrite 是离线实验，生产零实现。** 生产检索路径是直接向量检索，没有改写步骤。
3. **`run_kb_eval.py` 用暴力余弦（`embs @ q`）而非 ChromaDB 的 ANN 索引**——所以那个 92.9% 是**精确搜索结果**，不是生产近似搜索（HNSW）的结果。
4. **评测脚本只算 Recall@3 与 MRR，没有 NDCG。** 这两个指标在多 gold 场景会失明：Recall@3 是二值、丢位置；MRR 只认第一个命中。
5. **向量上限未处理干净的历史债**：`bge-large-zh-v1.5` 的 `max_seq_length` 是 512 token，早期未封顶的切片会被静默截断（零告警）。切片层已加 token 封顶 + 回归测试，但**已入库的旧向量需要重嵌入才生效**。
6. **`nodes.py:56` 有一处 SQLAlchemy 告警**：`SAWarning: Coercing Subquery object into a select() for use in IN()`。功能正常，但未来 SQLAlchemy 版本可能收紧为错误。
7. **本地测试对宿主代理环境敏感。** httpx 默认 `trust_env=True`；若环境变量 `NO_PROXY` 含"已带方括号的 IPv6"（如 `[::1]`），httpx 会生成畸形模式 `all://*[::1]` 并抛 `InvalidURL`，导致**测试无法收集**。这是本机环境问题，Linux CI 不受影响。
8. **`passlib` 已停止维护，与 `bcrypt >= 4.1` 不兼容。** passlib 1.7.4（2020 年后未再发版）首次 `hash()` 时会运行一个使用超 72 字节测试串的"环绕 bug 自检"，而 bcrypt ≥ 4.1 不再静默截断、会直接抛 `ValueError`。当前在 `requirements.txt` 中把 bcrypt 限定在 `>=4.0,<4.1` 兼容区间。**长期正解是移除 passlib、直接用 `bcrypt` 的 `hashpw` / `checkpw`**（约 10 行改动，bcrypt 哈希格式不变、存量用户密码不受影响），尚未执行。
9. **CI 分支过滤此前配错。** workflow 只监听 `push: branches: [main]`，而仓库实际工作分支是 `master`，因此**该 CI 从未被触发过**（现已修正为 `[master, main]`，并把默认分支同步改为 `master`）。`main` 是 2026-05 的旧版本分支，与 `master` 无共同祖先，**尚未合并或删除**。

---

## 架构

```mermaid
graph TB
    subgraph Frontend["前端 (React + Vite)"]
        A[图谱画布] --> B[编辑器]
        A --> C[RAG 对话面板]
    end

    subgraph Backend["后端 (FastAPI)"]
        D[REST API] --> E[节点/关系/标签 CRUD]
        D --> F[AI 分析服务]
        D --> G[RAG 对话服务]
        D --> H[文件导入服务]
    end

    subgraph Storage["存储层"]
        I[(MySQL 生产 / SQLite 轻量)]
        J[(ChromaDB 向量库<br/>每用户独立集合)]
    end

    subgraph AI["AI 层"]
        K[Anthropic Messages API<br/>base_url / model 可配置]
        L[sentence-transformers<br/>bge-large-zh-v1.5]
    end

    Frontend --> Backend
    E --> I
    G --> J
    F --> K
    G --> K
    H --> L
    L --> J

    style Frontend fill:#61dafb,color:#000
    style Backend fill:#009688,color:#fff
    style Storage fill:#ff9800,color:#fff
    style AI fill:#9c27b0,color:#fff
```

---

## 功能特性

| 功能 | 说明 |
|------|------|
| **知识图谱** | 力导向图谱可视化，节点可拖拽、缩放 |
| **AI 分析** | 自动提取笔记的摘要、分类、标签、重要性 |
| **RAG 对话** | 基于知识库内容的智能问答，**引用可溯源跳转** |
| **子知识点提取** | 自动提取 `##` 二级标题作为图谱子节点，支持跨笔记关联 |
| **Markdown 编辑** | 左右分栏编辑 + 实时预览 |
| **文件导入** | `.md` / `.txt` / `.docx` 单文件与批量导入 |
| **标签系统** | 彩色标签管理、按标签过滤、标签云 |
| **知识点级关联** | 可关联到具体知识点，而非仅笔记级别 |

---

## Agent 可靠性

- ReAct 循环 + 多工具自主选择；**每次工具调用只访问当前认证用户的知识库**（每用户独立向量集合）。
- **死循环检测**：连续多轮完全相同的工具调用即判定不收敛并强制收尾；另有 `MAX_ITERATIONS` 硬上限。
- **降级路径**：首次工具调用失败即降级为无工具的普通对话，不让用户卡死。
- 工具参数有边界限制；**知识库内容与网页内容均作为不可信数据处理**。
- **只有 Agent 工具实际返回的节点才可以作为引用输出**。
- 用户自定义模型密钥**加密保存**；生产启动必须显式配置签名密钥与加密密钥。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy 2.x + Alembic |
| 数据库 | MySQL（生产，`pymysql`）/ SQLite（轻量） |
| 前端 | React + Vite + Zustand |
| AI | Anthropic Messages API（`base_url` / `model` 可配置） |
| 向量检索 | ChromaDB + sentence-transformers（`bge-large-zh-v1.5`） |
| 其他 | `slowapi` 限流、`jieba` 分词、`ddgs` 网页搜索、`python-jose` + `passlib` 认证 |

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/happiness-cheng/knowledge-base.git
cd knowledge-base

# 2. 安装后端依赖
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 3. 配置（参考 ENVIRONMENT.md），在 backend 下创建 .env
#    DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/knowledge_base?charset=utf8mb4
#    AI_API_KEY=你的API Key
#    AI_BASE_URL=https://your-anthropic-compatible-endpoint
#    AI_MODEL_NAME=your_model_name

# 4. 建表（Alembic）
venv\Scripts\python -m alembic upgrade head

# 5. 安装前端依赖
cd ../frontend
npm install

# 6. 启动（Windows）
cd ..
start.bat
```

浏览器自动打开 **http://localhost:5173**

---

## 使用指南

1. **创建笔记**：左上角 **+ 新建**，输入标题与 Markdown 内容，保存。
2. **查看知识图谱**：笔记自动出现在画布上，点击节点展开详情。
3. **AI 分析**：节点详情中点击 **AI 分析**，自动提取摘要、分类、标签。
4. **关联知识点**：展开节点的子知识点（`##` 标题），在详情面板点击 **+ 添加关联**。
5. **RAG 对话**：右上角 **Chat**，提问后 AI 基于知识库回答并标注引用来源。

---

## 项目结构

```
knowledge-base/
├── backend/
│   ├── app/
│   │   ├── routers/          # API 路由（nodes, tags, relationships, graph, ai, chat, import）
│   │   ├── models/           # SQLAlchemy 数据模型
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   ├── services/         # 业务逻辑（AI 分析、RAG、Agent、文件导入）
│   │   └── utils/            # 工具函数（Markdown 清理与切分）
│   ├── eval/                 # 评测脚本与分层评测集（可复现的数字来源）
│   ├── alembic/              # 数据库迁移
│   └── tests/                # pytest 测试套件（135 项）
├── frontend/
│   └── src/
│       ├── components/       # React 组件（图谱、编辑器、对话、导入等）
│       ├── stores/           # Zustand 状态管理
│       ├── api/              # API 客户端
│       └── styles/           # CSS 样式
├── start.bat                 # 一键启动
├── ENVIRONMENT.md            # 环境配置说明
└── README.md                 # 本文件
```

---

## 测试

```bash
cd backend
venv/Scripts/python.exe -m pytest tests -q --tb=short
```

当前结果：**135 passed**（覆盖 CRUD、关系、标签、图谱、子知识点提取、导入、对话、迁移与 Agent 可靠性场景）。

前端生产构建：

```bash
cd frontend
npm run build
```

---

## 贡献

欢迎提 Issue 和 Pull Request。

## 许可证

[MIT](./LICENSE)
