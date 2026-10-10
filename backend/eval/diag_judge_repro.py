"""复现 live run 的 faithfulness 空返回。

已知：单独用小例子 + max_tokens=2000 → 正常。
未知：live run 里 44 条用例、3 并发、真实答案（10+ 条断言）下为什么 raw=""

本脚本按 live run 的确切调用方式跑（make_caller 的 max_tokens），
并把 finish_reason / usage / content 长度一起打出来定位。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
sys.stdout.reconfigure(encoding='utf-8')

import dsh_provider  # noqa: E402
import eval.generation_eval as ge  # noqa: E402
from app.env_sanitize import sanitize_no_proxy  # noqa: E402

sanitize_no_proxy()
from openai import OpenAI  # noqa: E402

cli = OpenAI(api_key=dsh_provider.load_key(), base_url=dsh_provider.BASE_URL)

# live run 里那条答案的真实断言（从 generation_eval_dsh.json 里取）
REAL_CLAIMS = [
    '进程和线程的主要区别如下：',
    '定义**：进程是操作系统进行**资源分配的基本单位**，拥有独立的地址空间；',
    '线程是 **CPU 调度的基本单位**，共享进程的内存和资源。',
    '特点**：进程隔离性强，创建/切换开销大；',
    '线程共享地址空间，切换开销小，但同步复杂，且一个线程崩溃可能影响整个进程。',
    '使用场景**：进程用于需要强隔离的独立服务，如微服务、浏览器多标签页；',
    '线程用于需要高性能并发的任务，如多核计算、GUI 线程。',
    '风险**：进程间通信（IPC）复杂、成本高；',
    '线程存在数据竞态、死锁、资源泄漏等并发风险。',
    '[doc:1] 另外，信号量的释放与获取不配对也会导致资源泄漏或死锁。',
]
CTX = '进程是资源分配的基本单位，线程是 CPU 调度的基本单位。线程存在数据竞态、死锁风险。'

user = ('CONTEXT:\n' + CTX + '\n\nCLAIMS:\n'
        + '\n'.join(f'{i}. {c}' for i, c in enumerate(REAL_CLAIMS)))

print('=== 按 make_caller 的确切参数复现（max_tokens=1024, temperature=0）===')
for model in (dsh_provider.JUDGE_MODEL, dsh_provider.GEN_MODEL):
    for mt in (1024, 512):
        r = cli.chat.completions.create(
            model=model, max_tokens=mt, temperature=0,
            messages=[{'role': 'system', 'content': ge.FAITH_SYS},
                      {'role': 'user', 'content': user}])
        ch = r.choices[0]
        c = ch.message.content or ''
        print(f'  {model:<18} mt={mt:<5} finish={ch.finish_reason:<8} '
              f'len={len(c):<5} usage={r.usage.completion_tokens:<5} head={c[:60]!r}')
