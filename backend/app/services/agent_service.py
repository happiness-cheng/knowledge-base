"""Agent 服务 — ReAct 循环核心，替代 chat_service.generate_chat_response()"""

import json
import re
import logging
from app.services.claude_client import claude_client
from app.services.agent_tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

AGENT_SYSTEM_PROMPT = """You are a knowledge base assistant with access to tools. You can search the knowledge base, look up node details, explore the knowledge graph, analyze relationships, and search the web.

SEARCH PRIORITY (strict order):
1. ALWAYS search_knowledge_base first when the user asks a question.
2. If search results are relevant, get_node_details for the most promising nodes to get full context.
3. If knowledge base search returns NO relevant results or the topic is NOT covered in the KB, use web_search to find information on the web.
4. You may combine KB results and web results if the KB has partial coverage.
5. If user asks about connections between topics, use analyze_relationships or query_graph.

CITATION RULES:
- KB sources: cite as [doc:ID] (e.g., [doc:3])
- Web sources: cite as [web:title](url)
- Always clearly indicate which parts come from KB vs web vs your general knowledge

RESPONSE FORMAT:
- Be concise. Use markdown formatting including tables where appropriate.
- If you found nothing in KB AND nothing on the web, say so honestly and give your best general knowledge answer."""

GENERAL_SYSTEM_PROMPT = """You are a knowledgeable assistant. Answer the user's question thoroughly using your general knowledge. Provide a clear, well-structured answer. Use markdown formatting for readability, including tables where appropriate."""


def _extract_citations(text: str) -> list[int]:
    """从回答中提取 [doc:123] 引用的节点 ID"""
    citations = re.findall(r'\[doc:(\d+)\]', text)
    return [int(c) for c in citations]


def _detect_loop(steps: list, window: int = 4) -> bool:
    """检测死循环：连续 window 次完全相同的工具调用"""
    tool_calls = [s for s in steps if s["type"] == "tool_call"]
    if len(tool_calls) < window:
        return False
    recent = tool_calls[-window:]
    signatures = [
        (s["tool_name"], json.dumps(s["tool_input"], sort_keys=True))
        for s in recent
    ]
    return len(set(signatures)) == 1


def _build_messages(conversation) -> list[dict]:
    """从数据库 conversation 构建 API 消息列表"""
    messages = []
    for msg in conversation.messages:
        messages.append({"role": msg.role, "content": msg.content})
    return messages


def run_agent(db, conversation, user_message_content: str, ai_search: bool = False, user_id: int = 1) -> dict:
    """
    运行 Agent 循环。

    Returns:
        {
            "content": str,           # 最终回答文本
            "source_ids": list[int],  # 引用的节点 ID
            "is_from_kb": bool,       # 是否来自知识库
            "found_in_kb": bool,      # 知识库是否找到了答案
            "steps": list[dict],      # Agent 推理步骤（供前端展示）
        }
    """
    # AI 搜索模式：不走 Agent，直接通用知识回答
    if ai_search:
        messages = _build_messages(conversation)
        messages.append({"role": "user", "content": user_message_content})
        try:
            content = claude_client.chat(
                system=GENERAL_SYSTEM_PROMPT,
                messages=messages,
            )
        except Exception as e:
            content = f"Error: {str(e)}"
        return {
            "content": content,
            "source_ids": [],
            "is_from_kb": False,
            "found_in_kb": False,
            "steps": [],
        }

    # Agent 模式：ReAct 循环
    messages = _build_messages(conversation)
    messages.append({"role": "user", "content": user_message_content})

    steps = []
    used_node_ids = set()
    web_sources = []  # 追踪联网搜索来源 [{title, url}]

    for iteration in range(MAX_ITERATIONS):
        try:
            resp = claude_client.chat_with_tools(
                system=AGENT_SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )
        except Exception as e:
            # 模型不支持 tools 参数时的降级处理
            logger.warning("Agent call failed (iteration %d): %s", iteration, e)
            if iteration == 0:
                # 第一次就失败 → 退化为普通聊天
                try:
                    content = claude_client.chat(
                        system=AGENT_SYSTEM_PROMPT,
                        messages=messages,
                    )
                    return {
                        "content": content,
                        "source_ids": [],
                        "is_from_kb": False,
                        "found_in_kb": True,
                        "steps": [],
                    }
                except Exception as e2:
                    return {
                        "content": f"Error: {str(e2)}",
                        "source_ids": [],
                        "is_from_kb": False,
                        "found_in_kb": False,
                        "steps": steps,
                    }
            break

        # 分析响应内容
        text_blocks = []
        tool_use_blocks = []
        for block in resp.content:
            if hasattr(block, "text"):
                text_blocks.append(block.text)
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_use_blocks.append(block)

        # 没有工具调用 → 最终回答
        if not tool_use_blocks:
            final_text = "\n".join(text_blocks) if text_blocks else "[No response]"
            steps.append({"type": "final_answer", "content": final_text})

            # 提取引用的节点 ID
            cited = _extract_citations(final_text)
            source_ids = list(used_node_ids | set(cited))

            # 判断是否从知识库找到了答案
            found_in_kb = len(used_node_ids) > 0 and any(
                p not in final_text for p in [
                    "NOT_FOUND_IN_KB", "I don't have", "没有找到", "无法在知识库中找到"
                ]
            )

            return {
                "content": final_text,
                "source_ids": source_ids,
                "is_from_kb": found_in_kb,
                "found_in_kb": found_in_kb,
                "steps": steps,
                "web_sources": web_sources,
            }

        # 有工具调用 → 执行工具
        messages.append({"role": "assistant", "content": resp.content})

        tool_results = []
        for tool_use in tool_use_blocks:
            tool_name = tool_use.name
            tool_input = tool_use.input
            tool_id = tool_use.id

            # 记录工具调用步骤
            steps.append({
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_id,
            })

            # 执行工具
            result = execute_tool(tool_name, tool_input, db, user_id=user_id)

            # 追踪搜索到的节点 ID
            if tool_name in ("search_knowledge_base", "get_node_details"):
                try:
                    result_data = json.loads(result)
                    if isinstance(result_data, list):
                        for item in result_data:
                            if "node_id" in item:
                                used_node_ids.add(item["node_id"])
                    elif isinstance(result_data, dict) and "id" in result_data:
                        used_node_ids.add(result_data["id"])
                except (json.JSONDecodeError, TypeError):
                    pass

            # 追踪联网搜索来源
            if tool_name == "web_search":
                try:
                    result_data = json.loads(result)
                    if isinstance(result_data, list):
                        for item in result_data:
                            if "url" in item:
                                web_sources.append({
                                    "title": item.get("title", ""),
                                    "url": item.get("url", ""),
                                })
                except (json.JSONDecodeError, TypeError):
                    pass

            # 记录工具结果步骤
            steps.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result[:500] + ("..." if len(result) > 500 else ""),
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

        # 死循环检测
        if _detect_loop(steps):
            logger.warning("Agent loop detected at iteration %d, forcing final answer", iteration)
            messages.append({
                "role": "user",
                "content": "You've made repeated tool calls. Please provide your best answer now based on what you've gathered.",
            })
            try:
                final_text = claude_client.chat(
                    system=AGENT_SYSTEM_PROMPT,
                    messages=messages,
                )
            except Exception as e:
                final_text = f"Agent encountered an error: {str(e)}"

            steps.append({"type": "final_answer", "content": final_text})
            cited = _extract_citations(final_text)
            source_ids = list(used_node_ids | set(cited))
            return {
                "content": final_text,
                "source_ids": source_ids,
                "is_from_kb": len(used_node_ids) > 0,
                "found_in_kb": len(used_node_ids) > 0,
                "steps": steps,
                "web_sources": web_sources,
            }

    # 达到最大迭代次数 → 强制输出最终回答
    messages.append({
        "role": "user",
        "content": "Maximum tool calls reached. Please provide your best answer now.",
    })
    try:
        final_text = claude_client.chat(
            system=AGENT_SYSTEM_PROMPT,
            messages=messages,
        )
    except Exception as e:
        final_text = f"Agent encountered an error: {str(e)}"

    steps.append({"type": "final_answer", "content": final_text})
    cited = _extract_citations(final_text)
    source_ids = list(used_node_ids | set(cited))
    return {
        "content": final_text,
        "source_ids": source_ids,
        "is_from_kb": len(used_node_ids) > 0,
        "found_in_kb": len(used_node_ids) > 0,
        "steps": steps,
        "web_sources": web_sources,
    }
