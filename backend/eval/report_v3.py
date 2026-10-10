"""打印评测集 v3 的逐条结果，定位"哪些 rank≠1、为什么"。

用到已有产物 eval/eval_set_v3.json（不重新检索），便于快速人工判读。
"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')

data = json.loads((BASE / 'eval' / 'eval_set_v3.json').read_text(encoding='utf-8'))
rows = data['results']

ans = [r for r in rows if r['gold_node'] is not None]
neg = [r for r in rows if r['gold_node'] is None]

print('=' * 118)
print(f"{'结果':<4}{'ID':<6}{'类型':<5}{'gold':<6}{'rank':<6}{'top1':<7}{'cos':<8}"
      f"{'top1 heading':<26}query")
print('-' * 118)
for r in ans:
    ok = 'OK' if r['rank'] == 1 else ('~~' if r['rank'] and r['rank'] <= 3 else 'XX')
    print(f"{ok:<4}{r['id']:<6}{r['note_type']:<5}{r['gold_node']:<6}{str(r['rank']):<6}"
          f"node{r['top1_node']:<3}{r['top1_cos']:<8.3f}"
          f"{(r['top1_heading'] or '')[:24]:<26}{r['query'][:40]}")

print('\n' + '=' * 118)
print('rank≠1 的用例（这些是优化靶子）:')
for r in ans:
    if r['rank'] != 1:
        print(f"  {r['id']} [{r['note_type']}] 期望 node{r['gold_node']}，"
              f"实际 rank={r['rank']}")
        print(f"     query  : {r['query']}")
        print(f"     top1   : node{r['top1_node']} heading={r['top1_heading']!r} "
              f"cos={r['top1_cos']:.3f}")

print('\n' + '=' * 118)
print('无答案层（检索层无阈值，一律返回最近邻）:')
for r in neg:
    print(f"  {r['id']} {r['query'][:36]:<38} top1=node{r['top1_node']} "
          f"cos={r['top1_cos']:.3f} heading={r['top1_heading']!r}")
