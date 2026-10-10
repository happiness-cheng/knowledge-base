"""从文本里抽取日期（用于"数据新鲜度"元数据）。

## 为什么放在 utils 而不是 eval
生产读路径需要它：把笔记的日期随检索结果一起送进 prompt，模型才能判断
"用户问的时间段，库里到底覆盖没覆盖"。这是 M5-35「数据新鲜度」。

## 实测背景（2026-10-10）
12 条笔记里**只有 1 条**标题含可解析日期（`# 交易日志 - 2026-05-20`），
其余全靠 DB 的 `created_at`。所以本函数是"锦上添花"，主信号是 created_at。
两者关系：`note_date`（被记录事件的日期）优先，取不到则退回 `created_at`（入库时间），
并在返回值里用 `date_source` 标明用的是哪个 —— **不能把入库时间当事件时间用**。
"""
import re
from datetime import date, datetime

# 支持 2026-05-20 / 2026/5/20 / 2026年5月20日 / 2026.5.20
_DATE_PAT = re.compile(r'(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})')


def parse_note_date(*texts: str) -> date | None:
    """从若干段文本里找**第一个**合法日期。找不到返回 None。

    只接受 2000~2099 年，避免把版本号 / 数量当成日期
    （如 `10.86`、`1.2.3` 这类三位点号不会被匹配，因为正则要求首位是 20xx）。
    """
    for t in texts:
        if not t:
            continue
        for m in _DATE_PAT.finditer(t):
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return date(y, mo, d)
            except ValueError:
                continue        # 例如 2026-13-45
    return None


def note_date_of(title: str | None, content: str | None,
                 created_at: datetime | None) -> tuple[str, str]:
    """返回 (ISO 日期字符串, 来源)。来源 ∈ {'title', 'content', 'created_at', 'unknown'}。

    优先级：标题 > 正文 > created_at。
    为什么标题优先：标题里的日期通常是**被记录事件**的日期（如"交易日志 2026-05-20"），
    而 created_at 是**笔记被创建/导入**的时间，两者可能差几个月，不能混用。
    """
    d = parse_note_date(title or '')
    if d:
        return d.isoformat(), 'title'
    # 正文只扫前 200 字：正文中段的日期更可能是内容里的举例，不代表笔记时效
    d = parse_note_date((content or '')[:200])
    if d:
        return d.isoformat(), 'content'
    if created_at:
        return created_at.date().isoformat(), 'created_at'
    return '', 'unknown'
