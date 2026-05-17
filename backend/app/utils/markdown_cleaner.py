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

    return sections
