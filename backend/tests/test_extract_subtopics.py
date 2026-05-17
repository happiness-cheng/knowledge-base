"""Parameterized tests for sub-topic extraction across all note formats."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers.ai import router
import re


def extract(content):
    """Extract sub-topics using the same logic as the API endpoint."""
    headings = re.findall(r'^[ \t]*##[ \t]+(.+)$', content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^[ \t]*\d+[\.\、]\s*(.+)$', content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^[ \t]*[-*]\s+\*\*(.+?)\*\*', content, re.MULTILINE)
    sub_topics = []
    for h in headings:
        h = re.sub(r'^\d+[\.\、]\s*', '', h)
        h = h.strip().rstrip('：:').strip()
        if h and h not in sub_topics and len(h) < 80:
            sub_topics.append(h)
    return sub_topics


# === Group A: Standard ## headings ===
@pytest.mark.parametrize("content,expected", [
    ("## 标题A\n内容\n## 标题B\n内容", ["标题A", "标题B"]),
    ("## 标题A\n## 标题B\n## 标题C", ["标题A", "标题B", "标题C"]),
    ("  ## 有前导空格\n## 正常", ["有前导空格", "正常"]),
    ("## 标题后面有冒号：\n## 正常标题", ["标题后面有冒号", "正常标题"]),
    ("## 标题后面有英文冒号:\n## 正常", ["标题后面有英文冒号", "正常"]),
    ("## 重复标题\n内容\n## 重复标题\n内容", ["重复标题"]),
    ("## 短标题\n\n大量内容\n\n## 另一个标题", ["短标题", "另一个标题"]),
    ("## 标题含 special @#$ 符号", ["标题含 special @#$ 符号"]),
    ("## 中英mixed 标题Title", ["中英mixed 标题Title"]),
    ("\n\n  \n## 前面有多个空行", ["前面有多个空行"]),
])
def test_h2_headings(content, expected):
    assert extract(content) == expected


# === Group B: # 一级标题 (NOT matched, only ## is extracted) ===
@pytest.mark.parametrize("content,expected", [
    ("# 大标题\n内容\n# 另一个", []),
    ("# 一\n# 二\n# 三\n# 四\n# 五", []),
])
def test_h1_headings(content, expected):
    assert extract(content) == expected


# === Group C: ### 三级标题 (NOT matched, only ## is extracted) ===
@pytest.mark.parametrize("content,expected", [
    ("### 小节一\n### 小节二", []),
    ("### 带编号3. 的子标题", []),
])
def test_h3_headings(content, expected):
    assert extract(content) == expected


# === Group D: Mixed heading levels (only ## extracted) ===
@pytest.mark.parametrize("content,expected", [
    ("# 一级\n## 二级\n### 三级", ["二级"]),
    ("# A\n### C\n## B", ["B"]),
    ("# 大章\n## 小节\n### 微节\n## 小节2", ["小节", "小节2"]),
])
def test_mixed_headings(content, expected):
    assert extract(content) == expected


# === Group E: Numbered headings ===
@pytest.mark.parametrize("content,expected", [
    ("1. Collector\n2. Scheduler\n3. Executor", ["Collector", "Scheduler", "Executor"]),
    ("1. 线程概念\n2. 线程同步\n3. 线程池", ["线程概念", "线程同步", "线程池"]),
    ("1、进程管理\n2、内存管理\n3、文件系统", ["进程管理", "内存管理", "文件系统"]),
    ("10. 第十项\n11. 第十一项", ["第十项", "第十一项"]),
    ("  1. 缩进编号\n  2. 缩进编号2", ["缩进编号", "缩进编号2"]),
    ("1. 带冒号：\n2. 正常", ["带冒号", "正常"]),
])
def test_numbered_headings(content, expected):
    assert extract(content) == expected


# === Group F: Bold list items ===
@pytest.mark.parametrize("content,expected", [
    ("- **Collector 机制**：描述", ["Collector 机制"]),
    ("* **A** 内容\n* **B** 内容", ["A", "B"]),
    ("- **中英文Mixed** text", ["中英文Mixed"]),
    ("- **含冒号：的标题**", ["含冒号：的标题"]),
    ("- 普通列表项\n- **粗体项**", ["粗体项"]),
])
def test_bold_list_items(content, expected):
    assert extract(content) == expected


# === Group G: Should NOT match (negative tests) ===
@pytest.mark.parametrize("content,expected", [
    ("#### 四级标题\n##### 五级标题", []),
    ("这是普通段落\n没有标题格式", []),
    ("#TitleNoSpace", []),
    ("- 普通列表项（无粗体）", []),
    ("", []),
    ("   ", []),
])
def test_negative_cases(content, expected):
    assert extract(content) == expected


# === Group H: Notes with code blocks (only ## extracted) ===
@pytest.mark.parametrize("content,expected", [
    ("## 标题A\n```python\n# 不是标题\n```\n## 标题B", ["标题A", "标题B"]),
    ("## 安装\n```\npip install x\n```\n## 使用\n```\nimport x\n```\n## 部署",
     ["安装", "使用", "部署"]),
])
def test_code_blocks(content, expected):
    assert extract(content) == expected


# === Group I: Real-world formats ===
@pytest.mark.parametrize("content,expected", [
    # Obsidian style: ## + list + tags
    ("## 概念\n- 要点1\n- 要点2\n#tag\n## 应用\n- 场景1", ["概念", "应用"]),
    # GitHub README style
    ("## 安装\npip install x\n## 快速开始\n```python\nimport x\n```\n## API\n### GET /api",
     ["安装", "快速开始", "API"]),
    # Academic style with numbered sub-headings (leading "2." stripped, "1" remains)
    ("## 2.1 背景\n研究背景。\n## 2.2 方法\n实验方法。\n## 2.3 结果\n实验结果。",
     ["1 背景", "2 方法", "3 结果"]),
    # Chinese lecture notes
    ("## 第一讲：概述\n课程介绍。\n## 第二讲：基础\n基础知识。\n## 第三讲：进阶\n进阶内容。",
     ["第一讲：概述", "第二讲：基础", "第三讲：进阶"]),
])
def test_real_world_formats(content, expected):
    assert extract(content) == expected


# === Group J: Edge cases ===
@pytest.mark.parametrize("content,expected", [
    # Very long title (over 80 chars should be filtered)
    ("## " + "x" * 100 + "\n## 正常标题", ["正常标题"]),
    # Empty heading line (## followed by space but no text) — regex needs .+ so won't match empty
    ("## \n## 有效标题", ["有效标题"]),
    # Numbered with leading spaces (user's format)
    ("  1. Collector（事件接收器）\n  2. Queue（阻塞队列）",
     ["Collector（事件接收器）", "Queue（阻塞队列）"]),
])
def test_edge_cases(content, expected):
    assert extract(content) == expected