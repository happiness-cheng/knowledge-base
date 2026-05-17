import re
from typing import List, Tuple
from app.services.claude_client import claude_client
from app.services.rag_service import retrieve_relevant_nodes
from app.models.chat import Conversation, Message, message_sources
from app.database import SessionLocal


def extract_citations(text: str) -> List[int]:
    """Extract node IDs from citations like [doc:123]."""
    citations = re.findall(r'\[doc:(\d+)\]', text)
    return [int(c) for c in citations]


def _ai_general_answer(conversation: Conversation, user_message_content: str) -> str:
    """Use AI general knowledge to answer."""
    system_prompt = (
        "You are a knowledgeable assistant. Answer the user's question "
        "thoroughly using your general knowledge. Provide a clear, "
        "well-structured answer. Use markdown formatting for readability, "
        "including tables where appropriate."
    )
    messages = []
    for msg in conversation.messages:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message_content})
    return claude_client.chat(system=system_prompt, messages=messages)


def generate_chat_response(db: SessionLocal, conversation: Conversation, user_message_content: str, ai_search: bool = False) -> dict:
    """
    Returns: {"content": str, "source_ids": list, "is_from_kb": bool, "found_in_kb": bool}
    """
    if ai_search:
        # Explicit AI search mode: skip RAG entirely
        response_text = _ai_general_answer(conversation, user_message_content)
        return {"content": response_text, "source_ids": [], "is_from_kb": False, "found_in_kb": False}

    # 1. Retrieve context (graceful fallback if RAG fails)
    try:
        retrieved_nodes = retrieve_relevant_nodes(user_message_content, top_k=5)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("RAG retrieval failed: %s", e)
        retrieved_nodes = []

    # 2. Build system prompt with context
    system_prompt = """You are a knowledge base assistant. Answer ONLY if the context documents contain the specific information the user is asking for.

Rules:
1. Read the user's question carefully. Identify EXACTLY what they want to know.
2. Check if the context documents contain that SPECIFIC information.
3. If YES: answer and cite sources as [doc:ID].
4. If NO (even if documents mention the topic but don't answer the specific question): respond with exactly "NOT_FOUND_IN_KB" and nothing else.

Example: User asks "Why TCP needs three handshakes". Documents only describe the three steps but not WHY. → Respond "NOT_FOUND_IN_KB".

<context>
"""
    for node in retrieved_nodes:
        system_prompt += f'<document id="{node["node_id"]}" title="{node["title"]}">{node["content"]}</document>\n'
    system_prompt += "</context>"

    # 3. Format message history
    messages = []
    for msg in conversation.messages:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message_content})

    # 4. Call Claude with KB context
    try:
        response_text = claude_client.chat(system=system_prompt, messages=messages)
    except Exception as e:
        response_text = f"Error generating response: {str(e)}"

    # 5. Check if KB had the answer
    not_found_patterns = ['NOT_FOUND_IN_KB', 'cannot find', '找不到', '无法在', '没有找到', '未找到', 'I cannot']
    is_not_found = any(p in response_text for p in not_found_patterns)

    if is_not_found:
        # KB didn't have the answer → automatically search with AI general knowledge
        try:
            ai_response = _ai_general_answer(conversation, user_message_content)
        except Exception as e:
            ai_response = f"Error: {str(e)}"
        return {"content": ai_response, "source_ids": [], "is_from_kb": False, "found_in_kb": False}

    # KB found the answer
    cited_node_ids = extract_citations(response_text)
    retrieved_node_ids = [n["node_id"] for n in retrieved_nodes]
    final_source_ids = list(set(cited_node_ids)) if cited_node_ids else list(set(retrieved_node_ids))

    return {"content": response_text, "source_ids": final_source_ids, "is_from_kb": True, "found_in_kb": True}
