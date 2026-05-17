import os
import re
from pathlib import Path
from app.services.rag_service import retrieve_relevant_nodes

def generate_chat_response(user_message_content: str, conversation_messages: list = None, ai_search: bool = False) -> tuple[str, list]:
    """Generate a chat response using the configured AI provider."""
    from app.config import settings
    from app.services.claude_client import claude_client
    if not claude_client.client:
        return "请先在设置中配置 API Key", []
    try:
        retrieved_nodes = retrieve_relevant_nodes(user_message_content, top_k=5)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("RAG retrieval failed: %s", e)
        retrieved_nodes = []
    context_text = ""
    source_ids = []
    if retrieved_nodes:
        context_text = "\n\n".join([
            f"[Source {i+1}: {node['title']}]\n{node['content'][:2000]}"
            for i, node in enumerate(retrieved_nodes)
        ])
        source_ids = [node['node_id'] for node in retrieved_nodes]
    system_prompt = """You are a helpful knowledge base assistant. Answer the user's question based on the provided knowledge base content.

Rules:
1. If relevant content exists in the knowledge base, base your answer primarily on that content
2. If no relevant content exists, say so honestly and answer from general knowledge
3. Keep answers concise and focused
4. Reference source numbers when citing specific information"""
    user_message = user_message_content
    if context_text:
        user_message = f"Knowledge Base Content:\n{context_text}\n\n---\n\nUser Question: {user_message_content}"
    messages = list(conversation_messages or [])
    messages.append({"role": "user", "content": user_message})
    try:
        response = claude_client.client.messages.create(
            model=claude_client.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text, source_ids
    except Exception as e:
        return f"Error: {str(e)}", []
