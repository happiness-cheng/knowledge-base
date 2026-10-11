import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# bge-large-zh-v1.5 的 embedding 上限 = 512 token（M5-03）
# content 预算 480：留 ~32 token 给 title（add_node_to_index 会拼 "title\ncontent" 一起编码）
MAX_CONTENT_TOKENS = 480

# 中英句末标点（断句锚点），分号也断（长句中间）
# 英文句号 `.` 只在「句号 + 空白 + 大写字母」处断（句边界），避免把 3.14 / e.g. 切断
_SENTENCE_SPLIT = re.compile(r'(?<=[。！？!?；;])|(?<=\.)(?=\s+[A-Z])')

# 标题判定：容忍前导空白（缩进的 `##` 也是标题，见 split_by_headings 的说明）
_H2_RE = re.compile(r'^\s*##\s+(.*)$')
_H3_RE = re.compile(r'^\s*###\s')


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


def _force_split(text: str, max_tokens: int) -> list[str]:
    """最后兜底：确保**任何**输入都被压到预算以内。

    ⚠️ 为什么必须存在（2026-10-10 实测 bug）：
    原 `_hard_split` **只按 `\\n` 切行**。遇到"单行 784 token、全文零换行"的输入
    （典型来源：PDF 粘贴、被压成一行的笔记、无标点的口述记录），循环只跑一轮就把
    整个 784 token 原样返回 —— **兜底函数在最需要它的时候失效**。
    后果：该块既超过 MAX_CONTENT_TOKENS(480)，也超过 bge 的 512 上限 ⇒
    embedding **静默截断**，向量只代表开头，检索质量被无声拉低。

    降级顺序：按标点断句 → 按空白/标点逐段 → 逐字符。
    逐字符是唯一**无前提**的保证：只要 max_tokens >= 1 就一定能收敛。
    """
    if _n_tokens(text) <= max_tokens:
        return [text]
    logger.warning('force split: %d tokens > %d, no usable boundary (len=%d chars)',
                   _n_tokens(text), max_tokens, len(text))
    # 1) 按标点断句（借 _iter_sentences，它会把超长"句子"整体产出）
    pieces = [s for s in _iter_sentences(text) if s.strip()]
    if len(pieces) > 1:
        out = []
        for p in pieces:
            out.extend(_force_split(p, max_tokens) if _n_tokens(p) > max_tokens else [p])
        return out
    # 2) 按空白/标点切成 token 级的碎片
    coarse = [p for p in re.split(r'(\s+|[，,、])', text) if p and p.strip()]
    if len(coarse) > 1:
        out, buf = [], ''
        for p in coarse:
            cand = buf + p
            if buf and _n_tokens(cand) > max_tokens:
                out.append(buf)
                buf = p
            else:
                buf = cand
        if buf.strip():
            out.append(buf)
        # 仍可能有单块超限（某个碎片本身太长）→ 继续下沉
        final = []
        for c in out:
            final.extend(_force_split(c, max_tokens) if _n_tokens(c) > max_tokens else [c])
        if all(_n_tokens(c) <= max_tokens for c in final):
            return final
    # 3) 逐字符（无前提保证）：按字符数估算切，切完再校验
    chars_per_chunk = max(1, int(len(text) * max_tokens / max(1, _n_tokens(text))))
    out = [text[i:i + chars_per_chunk] for i in range(0, len(text), chars_per_chunk)]
    # 若中文/英文混排导致估算偏小，再收敛一次
    if any(_n_tokens(c) > max_tokens for c in out):
        out = [text[i:i + max(1, chars_per_chunk // 2)]
               for i in range(0, len(text), max(1, chars_per_chunk // 2))]
    return [c for c in out if c]


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """按行贪心打包；**单行自身超预算时下沉到 _force_split**。

    修复点：原实现遇到"单行超限"时会把整行原样返回，破坏"所有块 <= max_tokens"的契约。
    现在每一块产出前都校验，超限就走 `_force_split`。
    """
    parts, buf = [], ''
    for line in text.split('\n'):
        # 单行本身就超预算 → 先冲刷 buf，再对该行强制切分
        if _n_tokens(line) > max_tokens:
            if buf.strip():
                parts.append(buf)
                buf = ''
            parts.extend(_force_split(line, max_tokens))
            continue
        cand = (buf + '\n' + line).strip() if buf else line
        if buf and _n_tokens(cand) > max_tokens:
            parts.append(buf)
            buf = line
        else:
            buf = cand
    if buf.strip():
        parts.append(buf)
    # 最终契约校验：任何残留超限块都强制切分
    out = []
    for p in parts:
        out.extend(_force_split(p, max_tokens) if _n_tokens(p) > max_tokens else [p])
    return out


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
    """按 `##` 标题切分，每块再按 token 预算二次切分。

    ⚠️ 标题判定必须**容忍前导空白**（2026-10-07 修）：
      旧代码 `line.startswith('## ')` 只认顶格标题。而笔记里从网页/PDF 粘贴或
      编辑器自动缩进的内容，标题常带前导空格（实测 node5「后端项目知识总结」：
      顶格 `##` 只有 1 个，缩进 `##` 有 7 个）。漏检后果：
        8 个小节被合并成 1 个 section → 再被按标点硬切成 4 块 →
        每块混多个主题 → 向量代表"一堆主题的平均" → 单主题查询被稀释。
      证据：`Collector(3)` 这个 chunk 实际装的是 Monitor/Redis/Lua 的内容，
      而 heading 元数据写的却是 `Collector(3)` —— **元数据与内容不符**。

    控制变量实测（同一批 12 条 query、同模型、同 top_k，只换本函数）：
      Recall@3  1.000 → 1.000（饱和，测不出）
      MRR       0.792 → 0.875（+10.5%）
      node5 组  0.810 → 0.929；node3/13 对照组未退化
    详见 exp_chunking_controlled.py。
    """
    sections = []
    current_title = "Untitled"
    current_lines = []

    for line in text.split('\n'):
        m2 = _H2_RE.match(line)
        if m2 and not _H3_RE.match(line):
            if current_lines:
                sections.append((current_title, '\n'.join(current_lines).strip()))
            current_title = m2.group(1).strip()
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
