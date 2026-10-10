"""分析生成层评测结果：找出未评分与零分用例的原因。

三个要查清的问题：
  1. faithfulness 只评了 29/44 —— 另外 15 条为什么没评分
  2. Q30 faithfulness=0.00 但 context_recall=1.00 —— 是生成幻觉、还是判定过严
  3. 有哪些用例的失败可以直接归因到"gold 没进上下文"
"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
d = json.loads((BASE / 'eval' / 'generation_eval_dsh.json').read_text(encoding='utf-8'))
cs = d['cases']

print('=' * 90)
print('1) faithfulness 未评分的用例及原因')
print('=' * 90)
low = []
for c in cs:
    if c['faithfulness'] is None:
        det = c['detail'].get('faithfulness', {})
        nc, ns = len(det.get('claims', [])), len(det.get('supported', []))
        low.append((c['id'], nc, ns, det.get('coverage'), det.get('error', '')))
        print(f"  {c['id']:<5} claims={nc:<3} verdicts={ns:<3} "
              f"coverage={det.get('coverage')} {det.get('error','')}")
print(f'  共 {len(low)} 条未评分')
if low:
    covs = [x[3] for x in low if x[3] is not None]
    if covs:
        import statistics
        print(f'  这些用例的覆盖率：中位 {statistics.median(covs):.2f} '
              f'最低 {min(covs):.2f} 最高 {max(covs):.2f}')
print('  ⇒ 覆盖率低 = 模型少回了 verdict（不是答案有问题）')

print()
print('=' * 90)
print('2) 零分与低分用例（faithfulness < 0.7）')
print('=' * 90)
for c in cs:
    f = c['faithfulness']
    if f is not None and f < 0.7:
        det = c['detail']['faithfulness']
        print(f"\n  {c['id']}  gold=node{c['ref_node']}  faithfulness={f:.2f}  "
              f"relevancy={c['answer_relevancy']:.2f}  ctx_recall={c['context_recall']:.2f}")
        print(f"  Q: {c['question']}")
        print(f"  A: {c['answer'][:260]!r}")
        print(f"  被判定为不支持的断言：")
        for u in det.get('unsupported', [])[:4]:
            print(f"    - {u[:110]}")

print()
print('=' * 90)
print('3) gold 没进上下文的用例（失败可直接归因到检索）')
print('=' * 90)
for c in cs:
    if not c['gold_in_context']:
        print(f"  {c['id']} gold=node{c['ref_node']}  "
              f"faithfulness={c['faithfulness']} relevancy={c['answer_relevancy']} "
              f"ctx_recall={c['context_recall']}")
        print(f"    Q: {c['question']}")
        print(f"    A: {c['answer'][:200]!r}")
