"""生成层评测运行器。

用法：
    python eval/run_generation_eval.py            # 真跑（需 LLM 可用）
    python eval/run_generation_eval.py --mock     # 用打桩判定器自检流程（不调网络）

设计要点见 eval/generation_eval.py 的模块 docstring。本文件的职责：
  1. 用生产读路径取上下文（rag_service.retrieve_relevant_nodes）
  2. 用 gold evidence 定位 reference（**不调 LLM 生成 reference**，避免循环论证）
  3. 调生成模型 -> 调判定模型 -> 汇总
  4. 结果落盘 eval/generation_eval_<mode>.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('KB_CHROMA_SUFFIX', '_prod')


def load_ev3():
    spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['ev3'] = mod
    spec.loader.exec_module(mod)
    return mod


def make_mock_judge(role: str = 'judge'):
    """打桩：不调网络，返回结构正确的内容，用于验证解析与聚合链路。

    role='judge'  返回判定用的 JSON（并故意套 ```json 代码块，验证宽松解析）
    role='gen'    返回一段多句答案（否则 faithfulness 的断言拆分为空）
    """
    calls = {'n': 0}

    def judge(system: str, user: str) -> str:
        calls['n'] += 1
        if role == 'gen':
            return ('第一句：这是打桩生成的第一条断言内容。'
                    '第二句：这是打桩生成的第二条断言内容。'
                    '第三句：这是打桩生成的第三条断言内容，带 [doc:1] 引用。')
        if '"verdicts"' in system:
            items = [ln for ln in user.splitlines() if ln.strip()[:2].rstrip('.').isdigit()]
            key = 'supported' if 'supported' in system else 'in_context'
            verdicts = [{'id': i, key: (i % 3 != 0)} for i in range(len(items))]
            return '```json\n' + json.dumps({'verdicts': verdicts}) + '\n```'
        if 'single QUESTION' in system:
            return json.dumps({'question': '（打桩）反向生成的问题？'})
        if 'QUESTION_A' in system:
            return json.dumps({'same': True, 'score': 0.75})
        return '{}'

    judge.calls = calls
    return judge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mock', action='store_true', help='用打桩判定器，不调网络')
    ap.add_argument('--provider', choices=['project', 'dsh'], default='project',
                    help='project=项目自己的 claude_client（当前不可用）；'
                         'dsh=DSH 自带 DeepSeek 通道')
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 条（调试用）')
    ap.add_argument('--top-k', type=int, default=3)
    ap.add_argument('--workers', type=int, default=4, help='并发线程数（远程 API）')
    args = ap.parse_args()

    from app.services import rag_service
    from app.utils.markdown_cleaner import split_by_headings
    import eval.generation_eval as ge

    ev3 = load_ev3()
    nodes = ev3.load_notes()
    split_cache = {nid: split_by_headings(c) for nid, (t, c) in nodes.items()}

    # ---- 生成器 / 判定器 ----
    if args.mock:
        gen = make_mock_judge('gen')
        judge = make_mock_judge('judge')
        mode = 'mock'
        model_name = 'MOCK'
    elif args.provider == 'dsh':
        sys.path.insert(0, str(BASE / 'eval'))
        import dsh_provider  # noqa: E402
        # 判定要逐条输出 verdict，且这两个模型有大量不可见的 token 消耗
        # （输出 284 字符却用掉 844 completion_tokens，实测），所以给足 16384；
        # 给 4096 时 13/44 条因 finish_reason=length 返回空内容。见 dsh_provider 注释。
        gen = dsh_provider.make_caller(dsh_provider.GEN_MODEL, max_tokens=8192)
        judge = dsh_provider.make_caller(dsh_provider.JUDGE_MODEL, max_tokens=16384)
        mode = 'dsh'
        model_name = f'gen={dsh_provider.GEN_MODEL} judge={dsh_provider.JUDGE_MODEL}'
    else:
        from app.services.claude_client import claude_client
        model_name = claude_client.model

        def gen(system, user):
            return claude_client.chat(system, [{'role': 'user', 'content': user}],
                                      max_tokens=1024)

        def judge(system, user):
            return claude_client.chat(system, [{'role': 'user', 'content': user}],
                                      max_tokens=512)
        mode = 'project'

    cases = [c for c in ev3.CASES if c[1] is not None]
    if args.limit:
        cases = cases[:args.limit]

    print(f'模式={mode}  模型={model_name}  用例={len(cases)} 条  '
          f'top_k={args.top_k}  并发={args.workers}  '
          f'集合={rag_service._get_user_collection(1).name}\n')

    def one(case):
        cid, nid, ntype, qsrc, query, head, tail = case
        chunks = split_cache[nid]
        want = ev3.verify_evidence(chunks, head, tail)
        # reference = 含 gold evidence 的那一块正文（可验证真值，非模型生成）
        reference = chunks[want][1] if want is not None else ''
        retrieved = rag_service.retrieve_relevant_nodes(
            query, top_k=args.top_k, user_id=1)
        gold_in_ctx = any(r['node_id'] == nid and r.get('chunk_index') == want
                          for r in retrieved)
        r = ge.evaluate_case(cid, nid, query, retrieved, reference, gen, judge)
        r.gold_in_context = gold_in_ctx
        return r

    results = []
    t_start = time.perf_counter()
    if args.workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(one, c): c[0] for c in cases}
            for fut in as_completed(futs):
                results.append(fut.result())
        results.sort(key=lambda x: x.cid)
    else:
        for c in cases:
            results.append(one(c))
    elapsed = time.perf_counter() - t_start

    print(f'{"ID":<5}{"gold":<6}{"gold在上下文中":<14}{"忠实性":<9}{"相关性":<9}'
          f'{"上下文召回":<10}{"延迟ms":<9}备注')
    print('-' * 96)
    for r in results:
        fmt = lambda v: ('-' if v is None else f'{v:.2f}')
        print(f'{r.cid:<5}{r.ref_node:<6}{("是" if r.gold_in_context else "否 ←"):<14}'
              f'{fmt(r.faithfulness):<9}{fmt(r.answer_relevancy):<9}'
              f'{fmt(r.context_recall):<10}{r.latency_ms:<9.0f}{r.error[:40]}')

    s = ge.summarize(results)
    print('\n' + '=' * 96)
    print(f'汇总（{mode}）：  总耗时 {elapsed:.0f}s')
    print(f'  用例 {s["n_cases"]}，成功评分 {s["n_scored"]}，调用失败 {s["n_errors"]}')
    print(f'  Faithfulness      {s["faithfulness"]}  (n={s["faithfulness_n"]})')
    print(f'  Answer Relevancy  {s["answer_relevancy"]}  (n={s["answer_relevancy_n"]})')
    print(f'  Context Recall    {s["context_recall"]}  (n={s["context_recall_n"]})')
    print(f'  gold 进上下文比例  {s["gold_in_context_rate"]}')
    print(f'  生成延迟中位       {s["median_latency_ms"]} ms')

    out = BASE / 'eval' / f'generation_eval_{mode}.json'
    out.write_text(json.dumps({
        'mode': mode, 'model': model_name, 'top_k': args.top_k,
        'summary': s,
        'cases': [{
            'id': r.cid, 'question': r.question, 'ref_node': r.ref_node,
            'gold_in_context': r.gold_in_context, 'answer': r.answer,
            'faithfulness': r.faithfulness, 'answer_relevancy': r.answer_relevancy,
            'context_recall': r.context_recall, 'latency_ms': r.latency_ms,
            'error': r.error, 'detail': r.detail,
        } for r in results],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已写: {out.name}')


if __name__ == '__main__':
    main()
