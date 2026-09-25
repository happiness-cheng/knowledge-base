"""教学演示：用真实的 agent_service.run_agent 跑一遍，打印每轮 messages 状态变化。
LLM 和工具执行用模拟对象替换（不调 API、不碰数据库）。
看完可删除此文件。
"""

import json
import sys

sys.path.insert(0, r"C:\Users\陈独秀\knowledge-base\backend")

from app.services import agent_service


class TextBlock:
    def __init__(self, text):
        self.text = text


class ToolUseBlock:
    def __init__(self, id, name, input):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class FakeResp:
    def __init__(self, content):
        self.content = content


CALL_COUNT = {"n": 0}


def summarize(content):
    if isinstance(content, str):
        return repr(content[:50])
    parts = []
    for b in content:
        if isinstance(b, ToolUseBlock):
            parts.append(f"tool_use({b.name}, {b.input})")
        elif isinstance(b, dict) and b.get("type") == "tool_result":
            parts.append(f"tool_result({str(b['content'])[:50]!r})")
        elif hasattr(b, "text"):
            parts.append(f"text({b.text[:30]!r})")
        else:
            parts.append(repr(b)[:50])
    return " + ".join(parts)


class FakeClient:
    def chat_with_tools(self, system, messages, tools, max_tokens=4096):
        CALL_COUNT["n"] += 1
        print(f"\n===== 第 {CALL_COUNT['n']} 次调用 LLM =====")
        print(f"  本次请求: system {len(system)} 字符 + tools {len(tools)} 个 + messages {len(messages)} 条")
        for i, m in enumerate(messages):
            print(f"    messages[{i}] role={m['role']!r}: {summarize(m['content'])}")
        if CALL_COUNT["n"] == 1:
            return FakeResp([
                TextBlock("我先搜索一下知识库。"),
                ToolUseBlock("toolu_001", "search_knowledge_base", {"query": "RAG 是什么"}),
            ])
        return FakeResp([
            TextBlock("RAG（检索增强生成）指先从知识库检索相关内容再让模型生成回答 [doc:1]")
        ])

    def chat(self, system, messages, max_tokens=4096):
        return "强制最终回答（本次演示未触发此路径）"


def fake_execute_tool(tool_name, tool_input, db, user_id=1):
    print(f"  >>> 工具执行: {tool_name}({tool_input})")
    return json.dumps(
        [{"node_id": 1, "title": "RAG入门", "content": "RAG = 检索增强生成，先检索再生成。"}],
        ensure_ascii=False,
    )


# 替换真实工具执行，避免依赖数据库
agent_service.execute_tool = fake_execute_tool


class FakeMsg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class FakeConversation:
    messages = [FakeMsg("user", "我上周问过你 Python 装饰器")]


result = agent_service.run_agent(
    db=None,
    conversation=FakeConversation(),
    user_message_content="RAG 是什么？",
    user_id=1,
    ai_client=FakeClient(),
)

print("\n===== 循环结束，Agent 返回 =====")
print(json.dumps(
    {k: v for k, v in result.items() if k != "steps"},
    ensure_ascii=False, indent=2,
))
print("\nsteps 时间线:")
for s in result["steps"]:
    print(" ", json.dumps(s, ensure_ascii=False)[:130])
