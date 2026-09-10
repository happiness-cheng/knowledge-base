import re


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


# 切片 size 兜底上限（字符）：超过则按句子二次切（M5-02：超长小节单向量会语义平均化）
MAX_SECTION_CHARS = 1200


def _split_long_section(text: str, max_chars: int = MAX_SECTION_CHARS) -> list[str]:
    """超长小节按句号二次切分，保证单 chunk 语义聚焦"""
    if len(text) <= max_chars:
        return [text]
    sentences = text.replace('。', '。|').replace('！', '！|').replace('？', '？|').split('|')
    chunks, buf = [], ''
    for s in sentences:
        if len(buf) + len(s) > max_chars and buf:
            chunks.append(buf)
            buf = s
        else:
            buf += s
    if buf:
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

    # size 兜底：超长小节二次切分，标题带序号区分（M5-02 长文档优化）
    bounded = []
    for title, content in sections:
        for i, chunk in enumerate(_split_long_section(content)):
            sub = f"{title}({i+1})" if i > 0 else title
            bounded.append((sub, chunk))
    return bounded
