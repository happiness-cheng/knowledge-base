"""拒答能力评测：负例层的生成指标。

## 为什么必须单独测这一层
负例（库里没有的提问）目前在 v3 评测集里**只测了检索层**，而检索层永远返回最近邻
（`collection.query` 没有"找不到"这个输出）。实测证据：
    正例最高余弦  0.671（D1「为什么需要堆内存」，答案确实在库里）
    负例最高余弦  0.675（N01「今天上证指数收盘多少」，库里有 5 月 20 日的指数）
⇒ **余弦阈值分不开"有"和"没有"**，拒答只能靠 LLM 读完整内容后判断
   （对应 agent_service.py:58-61 的 NOT_FOUND_IN_KB 判据）。

## 负例分两类，危险度不同
  完全无关（OUT_OF_SCOPE）：N02 写辞职信、N04 K8s —— 余弦低，模型容易识别
  **话题相邻但不完整（NEAR_MISS）**：N01 问"今天"但库里是 5 月 20 日的数据；
      N05 问"昨天那笔卖出"，库里只有 5 月 20 日的记录 —— **这类的危险在于
      检索会命中看似相关的块，模型可能拿旧数据当"今天"回答（时效性幻觉）**
      N03 binlog/redolog：库里只有 MySQL 的封锁/索引内容，缺这块知识

## 指标定义
  refusal_rate    正确拒答比例（回答里不含库外事实）
  hallucination   回答中出现了上下文没有的具体事实（复用 faithfulness 拆断言）
  stale_answer    拿上下文里的旧/别的事实充当答案（仅在 NEAR_MISS 上判定）
"""
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
# 引导：必须在导入任何 app 模块之前执行（设 DATABASE_URL、净化 NO_PROXY）。
# 注意：不要写 `import eval._bootstrap` —— `eval` 是内置函数名，且本目录不是包，
# 直接按文件名导入最稳。
import _bootstrap  # noqa: E402,F401
sys.stdout.reconfigure(encoding='utf-8')

import dsh_provider  # noqa: E402
import generation_eval as ge  # noqa: E402
from app.services import rag_service  # noqa: E402

REFUSAL_SYS = (
    "You are a strict judge. You are given a QUESTION, the CONTEXT that was available, "
    "and an ANSWER.\n"
    "\n"
    "For each of the following, decide true/false — they are INDEPENDENT questions:\n"
    "  refused        = the answer explicitly declines, saying the context does not "
    "contain the requested information, and does NOT supply the requested fact.\n"
    "  supplied_fact  = the answer states the specific fact the question asked for.\n"
    "  temporal_match = the time period of the supplied fact MATCHES the time period the "
    "question asks about (e.g. question asks 'today' but the fact is dated 2026-05-20). "
    "If no fact was supplied, set this to true.\n"
    "  object_match   = the entity the answer reports on is the entity the question asked "
    "about (e.g. question asks about 宁德时代 but the answer reports 茅台). If no entity "
    "was requested or none reported, set this to true.\n"
    "\n"
    "Output JSON only: {\"refused\":true|false,\"supplied_fact\":true|false,"
    "\"temporal_match\":true|false,\"object_match\":true|false,\"reason\":\"<short>\"}"
)


def judge_refusal(judge, question, contexts, answer, kb_date=''):
    ctx = '\n---\n'.join(contexts)[:3000]
    today = f'CURRENT DATE (for reference): {kb_date}\n' if kb_date else ''
    out = judge(REFUSAL_SYS,
                f'{today}QUESTION: {question}\n\nCONTEXT:\n{ctx}\n\nANSWER:\n{answer}')
    data = ge.parse_json_loose(out)
    if not isinstance(data, dict) or 'refused' not in data:
        return None, f'unparsable: {str(out)[:80]}'
    return data, data.get('reason', '')


def main():
    ev3 = __import__('importlib').util.spec_from_file_location(
        'ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
    mod = __import__('importlib').util.module_from_spec(ev3)
    sys.modules['ev3'] = mod
    ev3.loader.exec_module(mod)

    negatives = [c for c in mod.CASES if c[1] is None]
    # 人工标注每条的类别（决定"正确行为"是什么）
    # 判据：库里到底有没有这条信息 —— 由人读原文确定，不由模型判断
    KIND = {
        'N01': ('NEAR_MISS', '库里是 5/20 的指数，问"今天"→ 时效不匹配'),
        'N02': ('OUT_OF_SCOPE', '与库内容无关'),
        'N03': ('NEAR_MISS', '库里只有 MySQL 封锁/索引，无 binlog/redolog'),
        'N04': ('OUT_OF_SCOPE', 'K8s 与库内容无关'),
        'N05': ('NEAR_MISS', '"昨天那笔卖出"——库里只有 5/20 的记录'),
        'N06': ('NEAR_MISS', '"昨天大盘"——库里只有 5/20 一天的数据'),
        'N07': ('NEAR_MISS', '"今天扫描"——扫描记录只有 5/20'),
        'N08': ('NEAR_MISS', '"下午两点"——库里有 13:00:20，无 14:00'),
        'N09': ('NEAR_MISS', '宁德时代：库里只有茅台/平安银行/石化/五粮液等'),
        'N10': ('NEAR_MISS', '"上一笔交易赚多少"——无法确定哪笔是"上一笔"'),
        'N11': ('NEAR_MISS', '"这周"——库里只有一天（5/20）的数据'),
    }

    gen = dsh_provider.make_caller(dsh_provider.GEN_MODEL, max_tokens=8192)
    judge = dsh_provider.make_caller(dsh_provider.JUDGE_MODEL, max_tokens=16384)

    # ⚠️ 这里**不再注入任何硬编码日期**（上一版写死 KB_DATE/NOTES_LATEST，
    # 那只是用来证明问题所在，不是工程方案）。现在测真实链路：
    #   · 工具输出：agent_tools._handle_search 的原始 JSON（含 note_date/kb_latest_date）
    #   · 提示词：只根据上下文作答 + 生产同一条 DATA_FRESHNESS_RULES（共享常量）
    # 若模型仍能正确拒答，说明"日期随检索结果流转"这条生产修复有效。
    #
    # 为什么不用 AGENT_SYSTEM_PROMPT：它教模型"调用工具"，而本评测是**直接问**模型
    # （不起 Agent 循环），于是模型会输出工具调用文本（实测出现 DSML 格式的
    # `<｜｜DSML｜｜ invoke ...>`，判定器判定为"未作答"）。所以用 GENERATE_SYS 的
    # "只根据上下文回答"框架 + 同一套时效规则。
    from app.services.agent_service import AGENT_SYSTEM_PROMPT, DATA_FRESHNESS_RULES
    from app.services.agent_tools import _handle_search
    from app.database import SessionLocal

    # 一致性校验：共享常量必须真的在生产 system prompt 里（防两处漂移）
    assert DATA_FRESHNESS_RULES.splitlines()[1] in AGENT_SYSTEM_PROMPT, (
        'DATA_FRESHNESS_RULES 与 AGENT_SYSTEM_PROMPT 不一致 —— 生产提示词没同步')
    gen_sys = ge.GENERATE_SYS + '\n\n' + DATA_FRESHNESS_RULES

    print(f'负例 {len(negatives)} 条  集合={rag_service._get_user_collection(1).name}')
    print('真实链路：_handle_search 的 JSON + GENERATE_SYS + 生产时效规则（无硬编码日期）\n')

    def one(case):
        cid, _nid, _nt, _qs, question, _h, _t = case
        t0 = time.perf_counter()
        db = SessionLocal()
        try:
            tool_out = _handle_search({'query': question, 'top_k': 3}, db, user_id=1)
        finally:
            db.close()
        try:
            parsed = json.loads(tool_out)
            items = parsed if isinstance(parsed, list) else []
        except Exception:
            items = []
        ctxs = [it.get('content', '') for it in items]
        answer = gen(gen_sys, f'CONTEXT (JSON from search tool):\n{tool_out}\n\nQUESTION: {question}')
        verdict, reason = judge_refusal(judge, question, ctxs, answer)
        faith, fdet = ge.faithfulness(judge, answer, ctxs)
        return {
            'id': cid, 'kind': KIND[cid][0], 'why': KIND[cid][1],
            'question': question, 'answer': answer,
            'top1_node': items[0].get('node_id') if items else None,
            'top1_cos': (1 - items[0]['distance'] ** 2 / 2)
            if items and items[0].get('distance') is not None else None,
            'note_dates': [it.get('note_date') for it in items],
            'kb_latest_date': items[0].get('kb_latest_date') if items else None,
            'verdict': verdict, 'reason': reason, 'faithfulness': faith,
            'unsupported': fdet.get('unsupported', []),
            'latency_ms': (time.perf_counter() - t0) * 1000,
        }

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(one, c): c[0] for c in negatives}
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda x: x['id'])

    print(f'{"ID":<5}{"类别":<13}{"余弦":<8}{"拒答":<7}{"给了事实":<10}'
          f'{"时间对":<8}{"对象对":<8}{"忠实性":<8}')
    print('-' * 92)
    for r in results:
        v = r['verdict'] or {}
        faith = r['faithfulness']
        faith_s = '-' if faith is None else f'{faith:.2f}'
        mark = lambda x: ('是' if x else '否') if x is not None else '?'
        print(f'{r["id"]:<5}{r["kind"]:<13}{r["top1_cos"]:<8.3f}'
              f'{mark(v.get("refused")):<7}{mark(v.get("supplied_fact")):<10}'
              f'{mark(v.get("temporal_match")):<8}{mark(v.get("object_match")):<8}'
              f'{faith_s:<8}')

    n = len(results)
    refused = sum(1 for r in results if (r['verdict'] or {}).get('refused'))
    supplied = sum(1 for r in results if (r['verdict'] or {}).get('supplied_fact'))
    bad_time = sum(1 for r in results
                   if (r['verdict'] or {}).get('supplied_fact')
                   and (r['verdict'] or {}).get('temporal_match') is False)
    bad_obj = sum(1 for r in results
                  if (r['verdict'] or {}).get('supplied_fact')
                  and (r['verdict'] or {}).get('object_match') is False)
    unparsed = sum(1 for r in results if r['verdict'] is None)
    print('\n' + '=' * 92)
    print(f'汇总（n={n}）：')
    print(f'  正确拒答率        {refused}/{n} = {refused / n:.3f}')
    print(f'  给了事实（不该给）  {supplied}/{n} = {supplied / n:.3f}')
    print(f'    其中时间不匹配    {bad_time}   ← 时效性幻觉')
    print(f'    其中对象不匹配    {bad_obj}')
    print(f'  判定未解析         {unparsed}/{n}')
    for kind in ('NEAR_MISS', 'OUT_OF_SCOPE'):
        sub = [r for r in results if r['kind'] == kind]
        if not sub:
            continue
        rr = sum(1 for r in sub if (r['verdict'] or {}).get('refused'))
        print(f'  {kind:<14} n={len(sub):<3} 拒答 {rr}/{len(sub)} = {rr / len(sub):.3f}')

    print('\n逐条答案：')
    for r in results:
        v = r['verdict'] or {}
        print(f"\n  [{r['id']}] {r['kind']}  {r['question']}")
        print(f"    期望：拒答（{r['why']}）")
        print(f"    判定：refused={v.get('refused')} supplied={v.get('supplied_fact')} "
              f"temporal={v.get('temporal_match')} object={v.get('object_match')}")
        print(f"    理由：{r['reason'][:110]}")
        print(f"    答案：{r['answer'][:300]!r}")

    out = _BACKEND / 'eval' / 'refusal_eval_dsh.json'
    out.write_text(json.dumps({
        'notes_latest_data': NOTES_LATEST, 'eval_date': KB_DATE,
        'n': n, 'refused': refused, 'supplied_fact': supplied,
        'temporal_mismatch': bad_time, 'object_mismatch': bad_obj,
        'unparsed': unparsed, 'results': results,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已写: {out.name}')


if __name__ == '__main__':
    main()
