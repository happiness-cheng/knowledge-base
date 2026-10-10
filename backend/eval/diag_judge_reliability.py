"""判定器可靠性测试：同一个输入判 N 次，看分数是否稳定。

## 为什么必须做这件事
同一个答案（Q30，内容完全来自原文）被判为 faithfulness=0.00，
而同类答案（Q01）得 0.80。如果同一输入的多次判定结果差异很大，
那**任何基于它的结论都不可信**——这比"分数低"严重得多。

测三件事：
  1. 重复一致性：同输入判 3 次，分数的极差
  2. 明显正确 vs 明显编造：判定器能不能区分（这是判定器的底线能力）
  3. 不同模型（v4-pro vs flash）的差异
"""
import statistics
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
sys.stdout.reconfigure(encoding='utf-8')

import dsh_provider  # noqa: E402
import eval.generation_eval as ge  # noqa: E402

CTX = ['哈希表通过哈希函数将键映射到数组索引，实现平均 O(1) 的查找。'
       'BFS 广度优先搜索用队列。栈是 LIFO，队列是 FIFO。']

CASES = [
    ('明显正确', 'BFS（广度优先搜索）一般用**队列**，因为队列是 FIFO（先进先出）结构，适合按层遍历 [doc:8]。'),
    ('明显编造', 'BFS 一般用优先队列（堆）实现，因为需要按距离排序，复杂度是 O(V log V)。'
                '另外 Python 的 collections.deque 内部是用红黑树维护的。'),
    ('一半一半', 'BFS 用队列实现。另外哈希表最坏情况退化为 O(n)，'
                '而且 Python 的 dict 在 3.7 之后保持插入顺序。'),
]

# 判定器原样输出，不走 coverage 过滤，直接看分数与稳定性
def raw_score(judge, answer):
    import json as _json
    claims = ge.split_claims(judge, answer)
    listing = '\n'.join(f'{i}. {c}' for i, c in enumerate(claims))
    out = judge(ge.FAITH_SYS, f'CONTEXT:\n' + '\n---\n'.join(CTX) + f'\n\nCLAIMS:\n{listing}')
    det = ge.parse_json_loose(out)
    if not isinstance(det, dict) or 'verdicts' not in det:
        return None, f'len(out)={len(out)} head={out[:60]!r}'
    vs = [bool(v.get('supported')) for v in det['verdicts']
          if isinstance(v, dict) and 'supported' in v]
    if not vs:
        return None, 'no verdicts'
    return sum(vs) / len(vs), f'{len(vs)}/{len(claims)} verdicts'


for model in (dsh_provider.JUDGE_MODEL, dsh_provider.GEN_MODEL):
    j = dsh_provider.make_caller(model, max_tokens=16384)
    print(f'=== 判定模型 {model}（max_tokens=16384）===')
    for label, ans in CASES:
        scores, notes = [], []
        for _ in range(3):
            s, note = raw_score(j, ans)
            if s is not None:
                scores.append(s)
            notes.append(note)
        if scores:
            print(f'  {label:<8} 3 次: {[round(x,2) for x in scores]}  '
                  f'中位 {statistics.median(scores):.2f}  极差 {max(scores)-min(scores):.2f}')
        else:
            print(f'  {label:<8} 全部失败: {notes[0]}')
    print()
