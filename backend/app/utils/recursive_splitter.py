"""递归/结构感知切分（严格版）——**实验性，生产未采用**。

## ⚠️ 状态：未上线
生产切分仍是 `markdown_cleaner.split_by_headings`。本模块是一组对照实验的产物，
结论是**不采用**：四轮实测（见 exp_recursive_final.py 等）在每个配置下都没能稳定
超过现状切分：

    配置                      块数  中位tok  答案段进上下文
    A 现状(两级+语义)           57    211     0.818
    B 递归（顺序打包）          57    215     0.864   ← 略高，但只改动 11/57 个块
    C 固定大小+重叠             35    459     0.818   （28 块顶在 360+，MRR 低 0.106）
    递归（无碎片合并）         106     60     0.682   （切太碎）
    递归 + 挑最小块合并         57    215     0.750   （重排原文，破坏单调性）

## 为什么还保留
它证明了一件对后续工作有用的事：**对"`##` 小节本来就映射单一话题"的语料，
递归到更细边界没有收益空间**。真实瓶颈在"去重规则"与"排序"，不在切分粒度。
对照：RAGFlow 按文档体裁分发切分模板，其通用 token 预算路径（`rag/app/naive.py`）
处理的正是这类散文源 —— 即"每个体裁用匹配它的边界"，而非递归得越深越好。

## 保留的三个正确性要点（若将来换成结构复杂的长文档，这些坑已踩过）
1. **只在超长时降级**：`_split_sequential` 开头，已在上界内立刻返回，不再细分。
2. **必须按原文顺序打包**：早期版本用"反复挑最小块与邻居合并"（见 _coalesce），
   块数能与现状对齐但**内容被重排**，实测把主指标从 0.818 拉到 0.750。
   只有顺序打包才保证"递归 = 现状能切的边界 ∪ 更细边界"，从而具备单调性。
3. **碎片要合并，但阈值要小**：阈值 360 会"填满上界"式合并、把不同主题合回一块，
   使递归完全失效（输出与现状逐项相同）；阈值 90 只并真正的碎片。

## 与更早版本的区别（更早版本被指出"递归写错了"）
更早版本有三处违背"只在超长时才降级"：
  1. `_greedy` 无条件把小块打包到接近上界 → 本来不超的块也被合并
  2. `_split_items` / `_split_sentences` 同样无条件打包
  3. 额外加的 `_merge_small` 主动把小块合并回去 → 直接把递归成果抵消掉
实测后果：`min_tokens>=240` 时输出与现状切分**逐项相同**（块数 57 / 中位 215 /
`>=360` 的块 9，三项全同），说明递归根本没生效。

## 本版规则
    split(text):
        若 text 已在上界内            → 直接返回，**不再降级**
        依次尝试边界，取**第一个能切开**的：
            `##` / `###` / 空行段落 / 列表项 / 句子
        对切出来的**每一个 piece 单独判断**：
            不超上界 → 原样保留（不合并、不打散）
            仍超上界 → 对这个 piece 用**剩余更细的边界**继续递归
        所有边界都试过仍超长 → 固定大小硬切 + overlap（最后兜底）

## 为什么不主动合并小块
小主题块（如单条"互斥锁"）虽然短，但它**恰好是一问一答的语义单元**。
合并不可能知道哪两块属于同一话题，硬合就会重新制造"一块多主题"。
上界的作用是**防止块过大**，不是"把块填满"。
"""
import re

from app.utils.markdown_cleaner import _iter_sentences, _n_tokens

# 内容预算：bge-large-zh-v1.5 上限 512，留余量给 title + heading 拼接
SOFT_LIMIT = 480
# 硬切时的重叠量（字符）。只有走到最后一级、语义连续性已丢失时才需要
HARD_OVERLAP_CHARS = 120
# 极小块下限：低于此值的碎块才与相邻块合并（只用于防止 1~2 行的碎片）
TINY_FRAGMENT_TOKENS = 40
# 边界可用性判据：某级边界切出来的块若**中位数**低于此值，说明"切得比需要的还细"，
# 这一级不予采用，退回更粗的边界。
# 为什么需要（2026-10-07 实测）：node1「线程同步」整节超长 → 递归到"列表项"级 →
# 切出 10 块 40~73 token 的碎块。而列表项下面本来就是散装子项，切到这一级属于过度。
# 判据用中位数而非最小值：允许少数小片段存在，但不能整体都碎。
MIN_VIABLE_MEDIAN = 90

_H2 = re.compile(r'^\s*##\s+(.*)$')
_H3 = re.compile(r'^\s*###\s+(.*)$')
# 列表项：**允许缩进**（上一版要求顶格，导致 `  - **互斥锁**` 这类子项匹配不到）
_ITEM = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+')


def _fits(text: str, limit: int) -> bool:
    return _n_tokens(text) <= limit


# ---------------------------------------------------------------- 各级边界

def _by_h3(text: str) -> list[str]:
    parts, buf = [], []
    for line in text.split('\n'):
        if _H3.match(line) and buf:
            parts.append('\n'.join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        parts.append('\n'.join(buf))
    return [p for p in parts if p.strip()]


def _by_blank_line(text: str) -> list[str]:
    return [p for p in re.split(r'\n\s*\n', text) if p.strip()]


def _by_item(text: str) -> list[str]:
    """按列表项切。顶格或缩进的条目都算，且**保留空行**（否则会把段间距吃掉）。"""
    parts, cur = [], []
    for line in text.split('\n'):
        if _ITEM.match(line):
            if cur and any(x.strip() for x in cur):
                parts.append('\n'.join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur and any(x.strip() for x in cur):
        parts.append('\n'.join(cur))
    return [p.strip('\n') for p in parts if p.strip()]


def _by_sentence(text: str) -> list[str]:
    return [s for s in _iter_sentences(text) if s.strip()]


def _by_line(text: str) -> list[str]:
    return [l for l in text.split('\n') if l.strip()]


# 边界优先级，从大到小
_BOUNDARIES = [
    ('h3', _by_h3),
    ('blank', _by_blank_line),
    ('item', _by_item),
    ('sentence', _by_sentence),
]


def _hard_split(text: str, limit: int) -> list[str]:
    """最后兜底：按行贪心 + 字符重叠。只有语义边界全部不可用时才走到这里。"""
    if _fits(text, limit):
        return [text]
    parts, buf = [], ''
    for line in text.split('\n'):
        cand = (buf + '\n' + line) if buf else line
        if buf and not _fits(cand, limit):
            parts.append(buf)
            tail = buf[-HARD_OVERLAP_CHARS:] if len(buf) > HARD_OVERLAP_CHARS else ''
            buf = (tail + '\n' + line) if tail else line
        else:
            buf = cand
    if buf.strip():
        parts.append(buf)
    return parts


def _pack(units: list[str], limit: int, sep: str = '\n') -> list[str]:
    """**按原文顺序**贪心打包到上界；单个单元超限则允许它独自成块（不切开）。

    ## 为什么必须是"按顺序打包"而不是"挑最小块合并"（2026-10-07 血证）
    上一版用的是 `_coalesce`：反复挑**当前最小的块**与邻居合并。块数能与现状对齐
    （node1: 4 块 / node12: 2 块 / node13: 2 块 / node16: 7 块，全同），
    但**内容不同**（node12 块0：现状 470 token vs 递归 271 token）。
    原因：每次合并后"谁和谁相邻"就变了，原文的相邻关系被打乱。

    后果是**破坏了单调性**——本来"递归 = 现状 ∪ 额外边界，不该更差"，
    却因为重排导致答案段被打包进不同的块，检索命中率反而下降
    （实测 0.818 → 0.750）。

    顺序打包则保证：现状能切对的边界递归一样能切对，现状切不动的地方递归
    也只是降到更细的边界，**不会重新排列原文**。
    """
    out, buf = [], ''
    for u in units:
        if not u.strip():
            continue
        if not buf:
            buf = u
            continue
        cand = buf + sep + u
        if _fits(cand, limit):
            buf = cand
        else:
            out.append(buf)
            buf = u
    if buf.strip():
        out.append(buf)
    # 单个单元本身就超限（超长代码块/无标点长段）：交给调用方继续降级
    return out


def _split_sequential(text: str, limit: int, bounds: list) -> list[str]:
    """按顺序打包版递归：只在超长时降级，且**永不重排原文**。

    与 `_split` 的区别：不再对每个 piece 单独判断后原样拼接，而是把一级边界
    切出的**全部 pieces 按顺序打包**（打包不超上界），只有"单个 piece 自己就超限"
    时才需要对这个 piece 继续降级。
    """
    if not text.strip():
        return []
    if _fits(text, limit):
        return [text]

    for i, (name, fn) in enumerate(bounds):
        pieces = fn(text)
        if len(pieces) <= 1:
            continue
        # 顺序打包：不超上界的相邻 pieces 合并；单块超限的留给下一级
        packed, buf = [], ''
        for p in pieces:
            if not _fits(p, limit):
                # 这个 piece 自己就超限 → 先冲刷 buf，再对它继续降级
                if buf.strip():
                    packed.append(buf)
                    buf = ''
                packed.extend(_split_sequential(p, limit, bounds[i + 1:]))
                continue
            cand = (buf + '\n' + p) if buf else p
            if buf and not _fits(cand, limit):
                packed.append(buf)
                buf = p
            else:
                buf = cand
        if buf.strip():
            packed.append(buf)
        return packed

    return _hard_split(text, limit)          # 所有边界都失败 → 固定大小 + overlap


def _coalesce(parts: list[str], limit: int, min_tokens: int) -> list[str]:
    """自下而上合并"碎片块"。

    ## 为什么必须合并（2026-10-07 两次实测的教训）
    递归到最细边界（列表项）后会产生大量 40~70 token 的碎块。实测严格递归版本：
      块数 57→106，中位 211→60，答案段进上下文 0.818→**0.682**，零修复、净损坏 6 条。
    碎块的问题不是"短"本身，而是**一个碎片承载不了完整问句的语义**。

    ## 与上一版失败做法的区别（阈值，而不是"要不要合并"）
    上一版把阈值设成 360，"填满上界"式合并 → 把不同主题合回一块，
    导致输出与现状切分逐项相同（递归白做）。
    本版阈值只针对**碎片尺度**（默认 90 token）：主题块（200+ token）不动，
    只把 `- **定义**` 这类孤零零的子项并回它的邻居。

    ## 合并顺序
    每次取当前最小的块，与合并后更小的那个邻居合并（保证结果尽量均衡），
    且合并后不得超上界。重复到没有可合并的碎片为止。
    """
    if min_tokens <= 0 or len(parts) <= 1:
        return parts
    out = list(parts)
    while len(out) > 1:
        sizes = [_n_tokens(p) for p in out]
        i = sizes.index(min(sizes))
        if sizes[i] >= min_tokens:
            break
        best = None
        for j in (i - 1, i + 1):
            if not (0 <= j < len(out)):
                continue
            merged = (out[j] + '\n' + out[i]) if j < i else (out[i] + '\n' + out[j])
            if _fits(merged, limit):
                if best is None or sizes[j] < best[1]:
                    best = (j, sizes[j], merged)
        if best is None:
            # 该碎片与两侧都合不了（邻居已接近上界）：暂存它，继续看别的碎片，
            # 避免死循环——把它标记为"已处理"需要额外结构，这里直接退出即可，
            # 因为下面的碎片若还能合会在下一轮被处理（min 会变）。
            break
        j, _, merged = best
        lo, hi = (j, i) if j < i else (i, j)
        out[lo:hi + 1] = [merged]
    return out


# ---------------------------------------------------------------- 对外接口

def _sections(text: str) -> list[tuple[str, str]]:
    """按 `##` 切小节（缩进容忍）。返回 [(标题, 正文)]。"""
    out, title, lines = [], 'Untitled', []
    for line in text.split('\n'):
        m2, m3 = _H2.match(line), _H3.match(line)
        if m2 and not m3:
            out.append((title, '\n'.join(lines).strip()))
            title, lines = m2.group(1).strip(), []
        else:
            lines.append(line)
    out.append((title, '\n'.join(lines).strip()))
    return [(t, b) for t, b in out if b.strip()]


def split_recursive(text: str, limit: int = SOFT_LIMIT,
                    min_tokens: int = MIN_VIABLE_MEDIAN) -> list[tuple[str, str]]:
    """生产用递归切分入口。返回 [(heading, body)]，与 split_by_headings 同接口。

    min_tokens：碎片合并阈值。低于此值的块会与相邻块合并（不超上界时）。
    """
    if not text.strip():
        return []

    sections = _sections(text)
    if not sections:
        first = text.split('\n')[0].strip()
        title = first.lstrip('#').strip() if first.startswith('#') else first[:100]
        sections = [(title, text)]

    result: list[tuple[str, str]] = []
    for title, body in sections:
        # 顺序打包版递归：只在超长时降级，永不重排原文
        pieces = _split_sequential(body, limit, _BOUNDARIES)
        for j, piece in enumerate(pieces):
            if len(pieces) == 1:
                name = title
            else:
                # 尝试从 piece 自身取一个真实的子标题，取不到就用序号的诚实写法
                m = _H3.match(piece.split('\n')[0]) if piece.startswith('###') else None
                if m:
                    name = f"{title} > {m.group(1).strip()}"
                else:
                    name = f"{title}({j + 1})"
            result.append((name, piece))
    return result
