"""契约校验：所有切分产出的块都必须 <= MAX_CONTENT_TOKENS（且 <= 模型上限 512）。

为什么值得单独一个脚本：这是"块不超上限"的**唯一硬保证**。
2026-10-10 实测发现过反例：单行 784 token、全文零换行的输入产出 1 个 784 token 的块，
会被 embedding 静默截断（向量只代表开头）—— 属于最难发现的静默降质。

覆盖：真实笔记 12 条 + 合成语料 + 若干构造的边界输入。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.utils.markdown_cleaner import (  # noqa: E402
    MAX_CONTENT_TOKENS, _n_tokens, split_by_headings)

MODEL_LIMIT = 512          # bge-large-zh-v1.5 的 max_seq_length
BUDGET = MAX_CONTENT_TOKENS


def check(name, text):
    chunks = split_by_headings(text)
    over_budget = [(h, _n_tokens(b)) for h, b in chunks if _n_tokens(b) > BUDGET]
    over_model = [(h, _n_tokens(b)) for h, b in chunks if _n_tokens(b) > MODEL_LIMIT]
    status = 'OK' if not over_budget else 'FAIL'
    print(f'  [{status}] {name:<34} {len(chunks):>3} 块  '
          f'max={max((_n_tokens(b) for _, b in chunks), default=0):>4} tok')
    if over_budget:
        print(f'         超预算块: {over_budget[:5]}')
    return len(over_budget), len(over_model)


print('=== 边界输入（构造）===')
cases = [
    ('单行超长无标点', 'Kafka 分区分配策略决定了消费者组内每个消费者负责哪些分区' * 30),
    ('单行超长有标点', '这是一个很长的句子，' * 200),
    ('超长单行英文', 'The quick brown fox jumps over the lazy dog. ' * 150),
    ('超长代码块', '```\n' + 'x = 1  # comment line\n' * 400 + '```'),
    ('纯空白', '   \n\n  \t '),
    ('空串', ''),
    ('单字符', 'a'),
    ('超长标题行', '## ' + '标' * 2000),
    ('无换行超长中文', '中' * 6000),
]
bad = 0
for name, text in cases:
    b, m = check(name, text)
    bad += b

print('\n=== 真实笔记（12 条）===')
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)
nodes = ev3.load_notes()
for nid, (title, content) in sorted(nodes.items()):
    b, m = check(f'node{nid} {title[:20]}', content)
    bad += b

print('\n=== 合成语料（20 条）===')
src = (_BACKEND / 'eval' / 'build_synthetic_corpus.py').read_text(encoding='utf-8')
ns = {}
exec(compile(src.split('def main()')[0], 'sc', 'exec'), ns)
for nid, title, pattern, created, content in ns['N']:
    b, m = check(f'{nid} {pattern}', content)
    bad += b

print(f'\n{"=" * 70}')
print(f'结论：超预算块总数 = {bad}   '
      f'{"✅ 契约满足（所有块 <= %d token）" % BUDGET if bad == 0 else "❌ 存在违约"}')
if bad:
    sys.exit(1)
