"""对比两套 faithfulness 判据：

  严格版（当前 generation_eval.FAITH_SYS）：原文没写的具体细节一律 false
  宽松版（本脚本内定义）：允许"一步合理推理"（如 FIFO→按层遍历），
                          只把"引入原文没有的新事实/数字/机制/结论"判 false

判据好坏的标准不是"哪个分高"，而是**分辨力**：能否把明显正确的判高、
把明显编造的判低。用三类样本对照：
  S1 完全来自原文          期望高
  S2 原文 + 一步合理推理    期望中高（两版会有分歧）
  S3 引入原文没有的新事实   期望低
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

CTX = ['哈希表通过哈希函数将键映射到数组索引，实现平均 O(1) 的查找。\n'
       'BFS 广度优先搜索用队列。栈是 LIFO，队列是 FIFO。']

LENIENT = (
    "You are a fair fact-checking judge. For each CLAIM, decide whether it is SUPPORTED "
    "by the CONTEXT.\n"
    "\n"
    "RUBRIC:\n"
    "  supported = true  IF the context states the claim, OR the claim is a reasonable "
    "restatement, summary, or ONE-STEP inference from what the context states. Common "
    "background knowledge that merely explains a stated fact is acceptable.\n"
    "  supported = false IF the claim introduces a concrete new fact not in the context: "
    "a specific number, name, API, complexity bound, mechanism, or causal claim, or if it "
    "contradicts the context.\n"
    "\n"
    "EXAMPLES (context: \"BFS 广度优先搜索用队列。栈是 LIFO，队列是 FIFO。\"):\n"
    "  \"BFS 用队列实现。\"                    -> true  (stated)\n"
    "  \"BFS 用队列，因为需要按层遍历。\"      -> true  (one-step: FIFO 常用于层序遍历)\n"
    "  \"BFS 需要用优先队列，复杂度 O(V log V)。\" -> false (new fact + wrong)\n"
    "\n"
    "Output JSON only: {\"verdicts\":[{\"id\":<int>,\"supported\":true|false}]}."
)

SAMPLES = [
    ('S1 完全来自原文', 'BFS 用队列实现 [doc:8]。'),
    ('S2 原文+一步推理', 'BFS（广度优先搜索）一般用**队列**，因为队列是 FIFO（先进先出）结构，适合按层遍历 [doc:8]。'),
    ('S3 引入新事实', 'BFS 一般用优先队列（堆）实现，因为需要按距离排序，复杂度是 O(V log E)。'),
]

j = dsh_provider.make_caller(dsh_provider.JUDGE_MODEL, max_tokens=16384)


def score(system, answer):
    claims = ge.split_claims(j, answer)
    listing = '\n'.join(f'{i}. {c}' for i, c in enumerate(claims))
    out = j(system, 'CONTEXT:\n' + '\n---\n'.join(CTX) + f'\n\nCLAIMS:\n{listing}')
    data = ge.parse_json_loose(out)
    if not isinstance(data, dict):
        return None
    vs = [bool(v.get('supported')) for v in data.get('verdicts', [])
          if isinstance(v, dict) and 'supported' in v]
    return sum(vs) / len(vs) if vs else None


print(f'{"样本":<20}{"严格版":<12}{"宽松版":<12}')
print('-' * 46)
for label, ans in SAMPLES:
    a = score(ge.FAITH_SYS, ans)
    b = score(LENIENT, ans)
    print(f'{label:<20}{("-" if a is None else f"{a:.2f}"):<12}'
          f'{("-" if b is None else f"{b:.2f}"):<12}')

print('\n分辨力 = 严格/宽松版各自 (S1+S2)/2 - S3：')
for name, sysp in (('严格版', ge.FAITH_SYS), ('宽松版', LENIENT)):
    vals = [score(sysp, ans) for _, ans in SAMPLES]
    if all(v is not None for v in vals):
        sep = (vals[0] + vals[1]) / 2 - vals[2]
        print(f'  {name}: S1={vals[0]:.2f} S2={vals[1]:.2f} S3={vals[2]:.2f} → 区分度 {sep:+.2f}')
