"""验证归因：递归版到底在哪一步与现状分道扬镳？

假设 H：递归版在 `##` 层级与现状相同；差异**全部**来自"碎片合并"这一步——
        因为合并会改变"哪些句子被打包进同一个 480 token 块"，从而改变每个块的向量。

验证方法（逐块对比，不跑检索）：
  1. 打印两版在每个 node 上的块数
  2. 找出**块数相同但内容不同**的 node —— 这些就是"切分点被打包方式改变"的证据
  3. 用 min_tokens=0（关闭合并）对比：若差异显著减少，则 H 成立
"""
import importlib.util
import sys
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402
from app.utils.recursive_splitter import split_recursive  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()

variants = [
    ('现状 split_by_headings', split_by_headings),
    ('递归 min=0（关闭合并）', lambda t: split_recursive(t, 480, 0)),
    ('递归 min=90', lambda t: split_recursive(t, 480, 90)),
    ('递归 min=150', lambda t: split_recursive(t, 480, 150)),
]

print('每个 node 的块数：')
print(f'{"node":<6}{"title":<26}' + ''.join(f'{v[0][:12]:<14}' for v in variants))
print('-' * 100)
for nid, (title, content) in sorted(nodes.items()):
    counts = [len(sp(content)) for _, sp in variants]
    flag = '  ← 不同' if len(set(counts)) > 1 else ''
    print(f'{nid:<6}{title[:24]:<26}' + ''.join(f'{c:<14}' for c in counts) + flag)

print('\n' + '=' * 100)
print('逐块内容对比：现状 vs 递归 min=150（块数相同的 node，内容是否也一样）')
base = split_by_headings
rec = lambda t: split_recursive(t, 480, 150)
same_all = True
for nid, (title, content) in sorted(nodes.items()):
    b = [x[1] for x in base(content)]
    r = [x[1] for x in rec(content)]
    if len(b) != len(r):
        continue
    for i, (x, y) in enumerate(zip(b, r)):
        if x != y:
            same_all = False
            ratio = SequenceMatcher(None, x, y).ratio()
            print(f'\nnode{nid} 块{i}  块数相同但内容不同（相似度 {ratio:.3f}）')
            print(f'  现状 {_n_tokens(x):>4}tok: {x[:70]!r}')
            print(f'  递归 {_n_tokens(y):>4}tok: {y[:70]!r}')
            break
print(f'\n块数相同的 node 里，{"" if same_all else "存在"}内容差异')

# 关键数字：两版共有的块数（完全相同的块）
print('\n' + '=' * 100)
print('两版之间"完全相同的块"占比（越高说明差异越小）')
for name, sp in variants[1:]:
    tot = same = 0
    for nid, (title, content) in nodes.items():
        b = set(x[1] for x in base(content))
        r = [x[1] for x in sp(content)]
        tot += len(r)
        same += sum(1 for p in r if p in b)
    print(f'  {name:<26} 相同的块 {same}/{tot} = {same / tot:.1%}')
