"""诊断：gold 定位（verify_evidence）在两种切分策略下是否都成立。

上一轮 chunk 级 Hit@1 = 1/44 明显异常低，怀疑不是检索问题而是**测量问题**：
evidence 的 head/tail 落在同一语义单元时，若被递归切分拆到不同的块里，
verify_evidence 就返回 None，该用例被当成"检索失败"，实为"gold 定位失败"。

本脚本不编码、不检索，只对切分结果做定位检查，秒级完成。
"""
import importlib.util
import sys
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

for label, sp in (('A 现状', split_by_headings), ('B 递归', split_recursive)):
    unresolved = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        chunks = sp(nodes[nid][1])
        idx = ev3.verify_evidence(chunks, head, tail)
        if idx is None:
            # 看 head 和 tail 分别落在哪块，判断是"拆散了"还是"根本没写"
            h = [i for i, (_, b) in enumerate(chunks) if head and head in b]
            t = [i for i, (_, b) in enumerate(chunks) if tail and tail in b]
            unresolved.append((cid, nid, head, tail, h, t, len(chunks)))
    print(f'\n=== {label}：定位失败 {len(unresolved)} 条 ===')
    for cid, nid, head, tail, h, t, nc in unresolved:
        kind = '拆散' if (h and t and not (set(h) & set(t))) else ('head缺' if not h else 'tail缺')
        print(f'  {cid} node{nid} [{kind}] head={head!r}@块{h}  tail={tail!r}@块{t}  '
              f'（该 node 共 {nc} 块）')

# 看 node0（node1）在两种策略下的切分差异，理解"拆散"的来源
print('\n' + '=' * 90)
print('node1 的两种切分对比（互斥锁/条件变量/原子操作是否被拆开）')
for label, sp in (('A 现状', split_by_headings), ('B 递归', split_recursive)):
    print(f'\n--- {label} ---')
    for i, (h, b) in enumerate(sp(nodes[1][1])):
        marks = []
        for kw in ('互斥锁', '条件变量', '原子操作', '读写锁', '信号量'):
            if kw in b:
                marks.append(kw)
        print(f'  [{i}] {_n_tokens(b):>4}tok heading={h[:26]!r:<28} 含: {marks}')
