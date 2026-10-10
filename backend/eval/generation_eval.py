"""生成层评测（RAGAS 三指标的透明实现）—— 先建好，LLM 通路恢复即可跑。

## 为什么自己实现而不装 ragas
1. ragas 未安装，且它拖 datasets + langchain 全家桶（体积大、版本冲突风险高）
2. 自己做判定逻辑 = **每一步都能讲清楚**（面试时"我用 ragas 跑了个分"没有信息量；
   "我定义了 faithfulness 的原子断言判定 + 无 reference 的 context recall 变体"才有）
3. 需要的只是"给模型一个结构化 prompt，拿回可解析的 JSON"——30 行的事

## 三个指标的操作定义（不用 ragas 的术语堆砌，全部可判定）
| 指标 | 判定方法 | 需要什么 |
|---|---|---|
| **Faithfulness** | 把答案拆成原子断言 → 逐条问"该断言能否由检索上下文推出" → 比例 | 只需上下文 |
| **Answer Relevancy** | 用答案反向生成 N 个问题 → 与原问题算相似度/是否同指 | 只需原问题 |
| **Context Recall** | 把 reference 拆成原子事实 → 逐条问"该事实在检索上下文里有没有" → 比例 | **需 reference** |

### reference 从哪来（关键设计决策，避免"用模型评模型"的循环）
不用 LLM 生成 reference，而用**已知的 gold 出处文本**：
    reference := 含 gold evidence 的那一块的正文
这是**可验证的真值**（来自源文档），不是模型产物。
若 gold 分布在一个笔记的多块里，则取这些块的拼接。

### Context Recall 的已知偏差（必须交底）
因为 reference = gold 块，而检索若**返回了** gold 块，则 context recall 必然接近 1。
所以这个指标只在"检索漏掉了 gold 块"时才有区分度（对我们这批数据 = Q16 那条）。
它的价值是**验证检索层的结论**，不是独立的新信号。

## 调用契约（LLM 未接通时用 mock 也能跑通全流程）
    judge(system, user) -> str       单一入口，便于替换实现 / 打桩
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))

# ---------------------------------------------------------------- 判定器接口

JUDGE_MODEL_NAME = 'unknown'


def parse_json_loose(text: str):
    """从模型输出里抠出 JSON。

    为什么要宽松解析：判定模型经常在 JSON 外套 markdown 代码块、加解释性前缀。
    实测过（本项目 knowledge_extractor.py:39 直接 json.loads 就曾因代码块围栏失败）。
    """
    if not text:
        return None
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 退一步：抓第一个 {...} 或 [...]
    for pat in (r'\{.*\}', r'\[.*\]'):
        m = re.search(pat, t, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------- 三个指标

FAITH_SYS = (
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
    "CALIBRATION EXAMPLES (context: \"BFS 广度优先搜索用队列。栈是 LIFO，队列是 FIFO。\"):\n"
    "  \"BFS 用队列实现。\"                        -> true  (stated)\n"
    "  \"BFS 用队列，因为需要按层遍历。\"          -> true  (one-step inference)\n"
    "  \"BFS 需要用优先队列，复杂度 O(V log E)。\" -> false (new fact, and wrong)\n"
    "\n"
    "为什么用宽松判据（2026-10-10 实测）：严格版（原文没写的一律 false）会惩罚"
    "生成器正常地复述与解释原文，把 paraphrase 判成幻觉 —— 分辨力 (S1+S2)/2−S3 仅 +0.50，"
    "宽松版达 +1.00。见 eval/diag_faithfulness_rubric.py。\n"
    "\n"
    "Output JSON only, no prose: {\"verdicts\":[{\"id\":<int>,\"supported\":true|false}]}. "
    "Return exactly one verdict per claim, in the same order."
)

RELEV_SYS = (
    "You are a judge. Given an ANSWER, write the single QUESTION that this answer most "
    "likely answers. Output JSON only: {\"question\":\"...\"}."
)


def split_claims(judge, answer: str) -> list[str]:
    """把答案拆成原子断言。用规则切句而非模型（省一次调用、且更稳定）。"""
    parts = re.split(r'(?<=[。！？!?；;])|\n+|(?<=\.)(?=\s+[A-Z])', answer)
    out = []
    for p in parts:
        s = p.strip(' \t-*#>')
        # 过滤过短片段与纯格式行
        if len(s) >= 8 and not re.fullmatch(r'[\W_]+', s):
            out.append(s)
    return out


def faithfulness(judge, answer: str, contexts: list[str]) -> tuple[float | None, dict]:
    """答案的每个原子断言是否被检索上下文支持（无 reference 依赖）。"""
    claims = split_claims(judge, answer)
    if not claims:
        return None, {'claims': [], 'supported': []}
    ctx = '\n---\n'.join(contexts)
    listing = '\n'.join(f'{i}. {c}' for i, c in enumerate(claims))
    raw = judge(FAITH_SYS, f'CONTEXT:\n{ctx}\n\nCLAIMS:\n{listing}')
    data = parse_json_loose(raw)
    if not isinstance(data, dict) or 'verdicts' not in data:
        return None, {'claims': claims, 'raw': raw[:200], 'error': 'unparsable'}
    supported = [bool(v.get('supported')) for v in data['verdicts']
                 if isinstance(v, dict) and 'supported' in v]
    if not supported:
        return None, {'claims': claims, 'raw': raw[:200], 'error': 'no verdicts'}
    # 覆盖率检查：模型可能少回或多回 verdict。少回时分数会**静默偏高/偏低**，
    # 必须把覆盖率记进 detail，否则分数看着正常、实际只判了一部分断言。
    coverage = len(supported) / len(claims)
    detail = {
        'claims': claims,
        'supported': supported,
        'coverage': round(coverage, 3),
        'unsupported': [claims[i] for i, v in enumerate(supported)
                        if not v and i < len(claims)],
    }
    if coverage < 0.8:
        detail['error'] = f'low coverage: {len(supported)}/{len(claims)} verdicts'
        return None, detail          # 覆盖率过低时不给分，避免误报
    return sum(supported) / len(supported), detail


def answer_relevancy(judge, answer: str, question: str) -> tuple[float | None, dict]:
    """反向生成问题，看是否与原问题同指。

    ragas 的做法是生成 N 个问题再与原名算余弦；这里简化为生成 1 个 + 判定同指，
    省一次嵌入调用。**代价**：不稳定性更高（单样本）。
    """
    raw = judge(RELEV_SYS, f'ANSWER:\n{answer}')
    data = parse_json_loose(raw)
    if not isinstance(data, dict) or not data.get('question'):
        return None, {'raw': raw[:200], 'error': 'unparsable'}
    gen_q = str(data['question']).strip()
    # 同指判定：也在同一次调用里做会更省，但为可解释性单独走一次
    CHECK_SYS = (
        "You are a judge. Decide whether QUESTION_A and QUESTION_B ask about the same "
        "thing (same topic and same intent). Output JSON only: "
        "{\"same\":true|false,\"score\":0.0-1.0}"
    )
    raw2 = judge(CHECK_SYS, f'QUESTION_A: {question}\nQUESTION_B: {gen_q}')
    d2 = parse_json_loose(raw2)
    if isinstance(d2, dict) and 'score' in d2:
        try:
            return float(d2['score']), {'gen_question': gen_q, 'same': d2.get('same')}
        except (TypeError, ValueError):
            pass
    return None, {'gen_question': gen_q, 'raw': raw2[:200], 'error': 'unparsable'}


RECALL_SYS = (
    "You are a strict judge. Given a CONTEXT and a list of FACTS from a reference answer, "
    "decide for each fact whether it can be found in the CONTEXT. "
    "Output JSON only: {\"verdicts\":[{\"id\":<int>,\"in_context\":true|false}]}."
)


def context_recall(judge, contexts: list[str], reference: str) -> tuple[float | None, dict]:
    """reference 的原子事实有多少出现在检索上下文里（需 reference）。"""
    facts = split_claims(judge, reference)
    if not facts:
        return None, {'facts': []}
    ctx = '\n---\n'.join(contexts)
    listing = '\n'.join(f'{i}. {c}' for i, c in enumerate(facts))
    raw = judge(RECALL_SYS, f'CONTEXT:\n{ctx}\n\nFACTS:\n{listing}')
    data = parse_json_loose(raw)
    if not isinstance(data, dict) or 'verdicts' not in data:
        return None, {'facts': facts, 'raw': raw[:200], 'error': 'unparsable'}
    got = [bool(v.get('in_context')) for v in data['verdicts']
           if isinstance(v, dict) and 'in_context' in v]
    if not got:
        return None, {'facts': facts, 'raw': raw[:200], 'error': 'no verdicts'}
    coverage = len(got) / len(facts)
    detail = {'facts': facts, 'in_context': got, 'coverage': round(coverage, 3)}
    if coverage < 0.8:
        detail['error'] = f'low coverage: {len(got)}/{len(facts)} verdicts'
        return None, detail
    return sum(got) / len(got), detail


# ---------------------------------------------------------------- 单条评测

GENERATE_SYS = (
    "You are a knowledge base assistant. Answer the user's question using ONLY the "
    "provided context. Cite sources as [doc:NODE_ID]. If the context does not contain "
    "the answer, say so explicitly instead of guessing."
)


@dataclass
class CaseResult:
    cid: str
    question: str
    answer: str = ''
    contexts: list[str] = field(default_factory=list)
    ref_node: int | None = None
    ref_chunk: int | None = None
    gold_in_context: bool = False
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_recall: float | None = None
    detail: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str = ''


def evaluate_case(cid, ref_node, question, retrieved, reference, generator, judge) -> CaseResult:
    r = CaseResult(cid=cid, question=question, ref_node=ref_node)
    ctx_blocks = [c['content'] for c in retrieved]
    r.contexts = ctx_blocks
    r.ref_chunk = retrieved[0].get('matched_chunk') if retrieved else None

    ctx_text = '\n---\n'.join(
        f'[doc:{c["node_id"]}] {c["content"]}' for c in retrieved)
    t0 = time.perf_counter()
    try:
        r.answer = generator(GENERATE_SYS, f'CONTEXT:\n{ctx_text}\n\nQUESTION: {question}')
    except Exception as e:                      # LLM 未接通时不炸，记录错误
        r.error = f'{type(e).__name__}: {str(e)[:120]}'
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r
    r.latency_ms = (time.perf_counter() - t0) * 1000

    for name, fn in (('faithfulness', lambda: faithfulness(judge, r.answer, ctx_blocks)),
                     ('answer_relevancy', lambda: answer_relevancy(judge, r.answer, question)),
                     ('context_recall', lambda: context_recall(judge, ctx_blocks, reference))):
        try:
            val, det = fn()
        except Exception as e:
            val, det = None, {'error': f'{type(e).__name__}: {str(e)[:80]}'}
        setattr(r, name, val)
        r.detail[name] = det
    return r


def summarize(results: list[CaseResult]) -> dict:
    def avg(attr):
        vals = [getattr(x, attr) for x in results if getattr(x, attr) is not None]
        return (round(statistics.mean(vals), 4), len(vals)) if vals else (None, 0)
    f, fn = avg('faithfulness')
    a, an = avg('answer_relevancy')
    c, cn = avg('context_recall')
    errs = [x for x in results if x.error]
    return {
        'n_cases': len(results),
        'n_scored': len(results) - len(errs),
        'n_errors': len(errs),
        'faithfulness': f, 'faithfulness_n': fn,
        'answer_relevancy': a, 'answer_relevancy_n': an,
        'context_recall': c, 'context_recall_n': cn,
        'median_latency_ms': round(statistics.median([x.latency_ms for x in results]), 1)
        if results else None,
        'gold_in_context_rate': round(
            sum(1 for x in results if x.gold_in_context) / len(results), 4) if results else None,
    }
