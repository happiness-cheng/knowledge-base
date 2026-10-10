"""看判定器逐条 verdict 的原始输出，定位"全判 false"的原因。

上一轮结果：明显正确=0.00、明显编造=0.00、一半一半=0.50 且极差为 0
⇒ 确定性但判错。需要看 claims 怎么被切开的、逐条 verdict 长什么样。
"""
import json
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
sys.stdout.reconfigure(encoding='utf-8')

import dsh_provider  # noqa: E402
import eval.generation_eval as ge  # noqa: E402

CTX = ['哈希表通过哈希函数将键映射到数组索引，实现平均 O(1) 的查找。\n'
       'BFS 广度优先搜索用队列。栈是 LIFO，队列是 FIFO。']

ANS_OK = 'BFS（广度优先搜索）一般用**队列**，因为队列是 FIFO（先进先出）结构，适合按层遍历 [doc:8]。'
ANS_BAD = 'BFS 一般用优先队列（堆）实现，因为需要按距离排序，复杂度是 O(V log V)。'
ANS_HALF = 'BFS 用队列实现。另外哈希表最坏情况退化为 O(n)。'

j = dsh_provider.make_caller(dsh_provider.JUDGE_MODEL, max_tokens=16384)

for label, ans in (('明显正确', ANS_OK), ('明显编造', ANS_BAD), ('一半一半', ANS_HALF)):
    claims = ge.split_claims(j, ans)
    listing = '\n'.join(f'{i}. {c}' for i, c in enumerate(claims))
    out = j(ge.FAITH_SYS, 'CONTEXT:\n' + '\n---\n'.join(CTX) + f'\n\nCLAIMS:\n{listing}')
    data = ge.parse_json_loose(out)
    print(f'=== {label} ===')
    print(f'  claims ({len(claims)}):')
    for i, c in enumerate(claims):
        print(f'    {i}. {c[:70]!r}')
    print(f'  原始输出({len(out)} 字符): {out[:320]!r}')
    if isinstance(data, dict):
        print(f'  verdicts: {json.dumps(data.get("verdicts"), ensure_ascii=False)[:300]}')
    print()
