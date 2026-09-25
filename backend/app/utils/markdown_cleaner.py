import re
from functools import lru_cache

# bge-large-zh-v1.5 的 embedding 上限 = 512 token（M5-03）
# content 预算 480：留 ~32 token 给 title（add_node_to_index 会拼 "title\ncontent" 一起编码）
MAX_CONTENT_TOKENS = 480

# 中英句末标点（断句锚点），分号也断（长句中间）
# 英文句号 `.` 只在「句号 + 空白 + 大写字母」处断（句边界），避免把 3.14 / e.g. 切断
_SENTENCE_SPLIT = re.compile(r'(?<=[。！？!?；;])|(?<=\.)(?=\s+[A-Z])')


@lru_cache(maxsize=1)
def _get_tokenizer():
    """懒加载 bge tokenizer（与 rag_service 同模型），失败回退 None 走字符估算"""
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained('BAAI/bge-large-zh-v1.5')
    except Exception:
        return None


def _n_tokens(text: str) -> int:
    tok = _get_tokenizer()
    if tok is not None:
        return len(tok(text, add_special_tokens=False)['input_ids'])
    # 兜底：保守按 2 字符/token 估（中文），英文/代码只会更小，保证不超 512
    return max(1, len(text) // 2)


def clean_markdown(text: str) -> str:
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = text.split('\n')
    cleaned = []
    in_code = False
    for line in lines:
        if line.startswith('```'):
            in_code = not in_code
        cleaned.append(line)
    if in_code:
        cleaned.append('```')
    return '\n'.join(cleaned).strip()


def _iter_sentences(text: str):
    """逐句产出；``` 代码块作为整块产出，内部不按标点断"""
    in_code = False
    buf = ''
    code_buf = ''
    for line in text.split('\n'):
        if line.strip().startswith('```'):
            if in_code:
                code_buf += line + '\n'
                yield code_buf
                code_buf = ''
                in_code = False
            else:
                if buf.strip():
                    yield buf
                    buf = ''
                code_buf = line + '\n'
                in_code = True
            continue
        if in_code:
            code_buf += line + '\n'
            continue
        for p in _SENTENCE_SPLIT.split(line):
            if not p.strip():
                continue
            buf += p
            yield buf
            buf = ''
    if code_buf.strip():
        yield code_buf
    if buf.strip():
        yield buf


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """无标点硬切兜底：按行贪心打包（代码块/超长无标点段落）"""
    parts, buf = [], ''
    for line in text.split('\n'):
        cand = (buf + '\n' + line).strip() if buf else line
        if buf and _n_tokens(cand) > max_tokens:
            parts.append(buf)
            buf = line
        else:
            buf = cand
    if buf.strip():
        parts.append(buf)
    return parts


def _split_long_section(text: str, max_tokens: int = MAX_CONTENT_TOKENS) -> list[str]:
    """超长小节按 token 预算二次切分；中英标点断句；代码块内不分割"""
    if _n_tokens(text) <= max_tokens:
        return [text]
    chunks, buf = [], ''
    for s in _iter_sentences(text):
        # 单个"原子块"（如超长代码块）本身就超预算 → 按行硬切
        if _n_tokens(s) > max_tokens:
            if buf:
                chunks.append(buf)
                buf = ''
            chunks.extend(_hard_split(s, max_tokens))
            continue
        cand = (buf + s).strip()
        if buf and _n_tokens(cand) > max_tokens:
            chunks.append(buf)
            buf = s
        else:
            buf = cand
    if buf.strip():
        chunks.append(buf)
    return chunks


def split_by_headings(text: str) -> list[tuple[str, str]]:
    sections = []
    current_title = "Untitled"
    current_lines = []

    for line in text.split('\n'):
        if line.startswith('## ') and not line.startswith('### '):
            if current_lines:
                sections.append((current_title, '\n'.join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        content = '\n'.join(current_lines).strip()
        if content:
            sections.append((current_title, content))

    if not sections:
        first_line = text.split('\n')[0].strip() if text.strip() else "Untitled"
        if first_line.startswith('#'):
            title = first_line.lstrip('#').strip()
        else:
            title = first_line[:100]
        sections = [(title, text)]

    bounded = []
    for title, content in sections:
        for i, chunk in enumerate(_split_long_section(content)):
            sub = f"{title}({i+1})" if i > 0 else title
            bounded.append((sub, chunk))
    return bounded
