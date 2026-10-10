"""查看拒答评测的汇总与关键个案（N10 是唯一未拒答的）。"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
d = json.loads((BASE / 'eval' / 'refusal_eval_dsh.json').read_text(encoding='utf-8'))

print('=== 汇总 ===')
for k in ('n', 'refused', 'supplied_fact', 'temporal_mismatch',
          'object_mismatch', 'unparsed'):
    print(f'  {k:<18} = {d[k]}')
print(f"  notes_latest_data  = {d.get('notes_latest_data')}")
print(f"  eval_date          = {d.get('eval_date')}")

for target in ('N10', 'N01', 'N05'):
    for r in d['results']:
        if r['id'] != target:
            continue
        print(f"\n=== {r['id']}  [{r['kind']}]  {r['question']} ===")
        print(f"  期望: {r['why']}")
        print(f"  判定: {json.dumps(r['verdict'], ensure_ascii=False)}")
        print(f"  答案: {r['answer'][:400]}")
