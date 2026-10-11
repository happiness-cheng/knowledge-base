"""定位 split_by_headings 的"超长块漏切"：784 token 的段落为何产出 1 块。"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.utils.markdown_cleaner import (  # noqa: E402
    MAX_CONTENT_TOKENS, _hard_split, _iter_sentences, _n_tokens, _split_long_section,
    split_by_headings)

# 取出那条无标点长文
src = open(_BACKEND / 'eval' / 'build_synthetic_corpus.py', encoding='utf-8').read()
ns = {}
exec(compile(src.split('def main()')[0], 'sc', 'exec'), ns)
text = next(c for nid, t, p, cr, c in ns['N'] if p == 'long_no_punct')

print(f'原文 token = {_n_tokens(text)}   长度 = {len(text)} 字符   '
      f'预算 = {MAX_CONTENT_TOKENS}')
print(f'含句末标点？  。={text.count("。")}  ！={text.count("！")}  ？={text.count("？")}  '
      f'；={text.count("；")}  ". "={text.count(". ")}')
print(f'含换行？ {text.count(chr(10))}')

sents = list(_iter_sentences(text))
print(f'\n_iter_sentences 产出 {len(sents)} 个"句子"，各自 token：'
      f'{[_n_tokens(x) for x in sents]}')

print(f'\n_split_long_section 产出 {len(_split_long_section(text))} 块，'
      f'各块 token：{[_n_tokens(x) for x in _split_long_section(text)]}')
print(f'_hard_split 产出 {len(_hard_split(text, MAX_CONTENT_TOKENS))} 块，'
      f'各块 token：{[_n_tokens(x) for x in _hard_split(text, MAX_CONTENT_TOKENS)]}')

print(f'\nsplit_by_headings 产出 {len(split_by_headings(text))} 块：'
      f'{[(h, _n_tokens(b)) for h, b in split_by_headings(text)]}')
