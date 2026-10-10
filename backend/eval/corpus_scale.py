"""量一下语料真实规模：决定"要不要 RAG"这个方案选择的关键数字。

三组数字：
  1. 全部笔记 token 总量        → 能否直接塞进长上下文（bge-m3 8192 / 现代模型 128k+）
  2. 单条笔记 token 分布        → 有多少条笔记本身就超 512（换模型的收益面）
  3. 切块后 token 分布          → 当前 57 块的实际大小
"""
import importlib.util
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()

print('=' * 88)
print('1) 单条笔记 token 规模')
print(f"{'node':<6}{'title':<30}{'字符':<8}{'token':<8}{'超512?':<9}{'块数'}")
print('-' * 88)
total_tok = 0
total_chars = 0
over512 = 0
for nid, (title, content) in sorted(nodes.items()):
    t = _n_tokens(content)
    chunks = split_by_headings(content)
    total_tok += t
    total_chars += len(content)
    if t > 512:
        over512 += 1
    print(f"{nid:<6}{title[:28]:<30}{len(content):<8}{t:<8}"
          f"{('是' if t > 512 else '否'):<9}{len(chunks)}")
print('-' * 88)
print(f'  合计：{len(nodes)} 条笔记  {total_chars} 字符  ≈ {total_tok} token')
print(f'  超过 512 token 的笔记：{over512}/{len(nodes)} 条'
      f'（这些笔记的尾部在换模型前注定被静默截断）')

print('\n' + '=' * 88)
print('2) 切块后 token 分布（当前策略，预算 480）')
all_chunks = []
for nid, (title, content) in nodes.items():
    for heading, body in split_by_headings(content):
        all_chunks.append((nid, heading, _n_tokens(body), len(body)))
toks = sorted(c[2] for c in all_chunks)
print(f'  共 {len(all_chunks)} 块   min={toks[0]}  中位={toks[len(toks) // 2]}  max={toks[-1]}')
print(f'  分布: ', end='')
for lo, hi in ((0, 50), (50, 100), (100, 200), (200, 300), (300, 400), (400, 481)):
    n = sum(1 for t in toks if lo <= t < hi)
    print(f'{lo}-{hi}:{n}  ', end='')
print()
print('  最大的 6 块（这些是"稀释向量"的嫌疑对象）:')
for nid, heading, t, ch in sorted(all_chunks, key=lambda c: -c[2])[:6]:
    print(f'    node{nid:<3} {t:>4} token ({ch:>5} 字符)  heading={heading[:36]!r}')

print('\n' + '=' * 88)
print('3) 方案可行性数字')
print(f'  · 全部笔记塞进单个 prompt：≈ {total_tok} token')
print(f'    - 现代长上下文模型（128k）完全放得下；GPT-4o/Claude 200k 更是绰绰有余')
print(f'    - 当前 bge-large-zh-v1.5 上限 512 token/块 ⇒ 必须切块检索')
print(f'  · 换 bge-m3（8192 上限）后：单条笔记最大 {max(_n_tokens(c) for _, c in nodes.values())} token，'
      f'**整条笔记可直接作为一块**，无需切分')
print(f'  · 但代价：换模型必须全量重嵌入 + 重标注（新旧向量不同空间）')
