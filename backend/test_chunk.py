import sys
sys.path.insert(0, 'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
from app.utils.markdown_cleaner import split_by_headings, _n_tokens, _split_long_section

def report(name, text):
    chunks = _split_long_section(text)
    toks = [_n_tokens(c) for c in chunks]
    over = sum(1 for t in toks if t > 512)
    print(f"[{name}] chunks={len(chunks)} max_tok={max(toks)} over512={over}")

# 1. 英文散文（洞1：无 。！？，英文 . 不参与 → 曾是 1 个 chunk 2002 token）
en = ("This is a long English paragraph about computer systems and their design trade-offs. " * 200)
report("English", en)

# 2. 中文长段（应照常按 。！？ 断）
zh = "这是第一个中文句子。" + "这是第二个中文句子！" * 100
report("Chinese", zh)

# 3. 代码块（``` 内不可断）
code = "```python\n" + "def f():\n    return 1\n" * 200 + "```\n" + "后面还有中文说明。" * 10
report("CodeBlock", code)

# 4. 真实最长笔记 id=3（4095 字符，曾是一个 2000 token 的向量）
import sqlite3
c = sqlite3.connect(r'C:/Users/陈独秀/.knowledge_base/knowledge.db')
content = c.execute("SELECT content FROM knowledge_nodes WHERE id=3").fetchone()[0]
report("node3-C++", content)

# 5. 真实 id=5 后端总结（3489 字符）
content5 = c.execute("SELECT content FROM knowledge_nodes WHERE id=5").fetchone()[0]
report("node5-backend", content5)
