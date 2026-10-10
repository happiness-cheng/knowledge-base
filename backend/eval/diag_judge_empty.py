"""诊断：判定模型返回空内容的原因。

背景：生成层评测里 faithfulness 总是 unparsable，detail 显示 raw=""（空字符串）。
可能原因：
  H1 completion 被 max_tokens 截断（10 条断言需要的输出较长）
  H2 模型把内容放进了 reasoning_content 之类的非标准字段
  H3 模型需要不同的 prompt（比如必须显式要求"不要思考直接输出"）
本脚本把原始响应整体打印出来，逐个证伪。
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

claims = [f'断言{i}：这是第{i}条测试断言内容，用来测试解析是否正常。' for i in range(10)]
user = ('CONTEXT:\n栈空间很小，堆可以运行时分配。\n\nCLAIMS:\n'
        + '\n'.join(f'{i}. {c}' for i, c in enumerate(claims)))

for model in (dsh_provider.JUDGE_MODEL, dsh_provider.GEN_MODEL):
    for mt in (2000,):
        r = cli.chat.completions.create(
            model=model, max_tokens=mt, temperature=0,
            messages=[{'role': 'system', 'content': ge.FAITH_SYS},
                      {'role': 'user', 'content': user}])
        ch = r.choices[0]
        content = ch.message.content or ''
        # 打印 message 的全部字段（找出内容到底在哪个字段）
        extra = {k: v for k, v in vars(ch.message).items() if k != 'content'} \
            if hasattr(ch.message, '__dict__') else {}
        print(f'=== model={model} max_tokens={mt} ===')
        print(f'  finish_reason = {ch.finish_reason}')
        print(f'  content 长度  = {len(content)}')
        print(f'  content 前150 = {content[:150]!r}')
        print(f'  其它字段      = {list(extra.keys())}')
        for k, v in extra.items():
            if v:
                print(f'    {k}: len={len(str(v))} 前100={str(v)[:100]!r}')
        print(f'  usage = prompt {r.usage.prompt_tokens} / completion {r.usage.completion_tokens}')
        print()
