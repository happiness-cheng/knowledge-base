"""Tests for /api/chat endpoints."""
from unittest.mock import patch


class TestConversation:
    def test_create_conversation(self, client):
        resp = client.post("/api/chat/conversations", json={"title": "测试对话"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "测试对话"
        assert data["id"] > 0

    def test_list_conversations(self, client):
        client.post("/api/chat/conversations", json={"title": "C1"})
        client.post("/api/chat/conversations", json={"title": "C2"})
        convs = client.get("/api/chat/conversations").json()
        assert len(convs) == 2

    def test_get_conversation_with_messages(self, client):
        conv = client.post("/api/chat/conversations", json={"title": "T"}).json()
        # Send a message (AI response is mocked in conftest)
        with patch("app.services.chat_service.generate_chat_response", return_value=("AI 回复", [])):
            msg = client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "你好"},
            )
        assert msg.status_code == 200
        # Get conversation detail
        detail = client.get(f"/api/chat/conversations/{conv['id']}").json()
        assert len(detail["messages"]) >= 1

    def test_get_conversation_not_found(self, client):
        resp = client.get("/api/chat/conversations/99999")
        assert resp.status_code == 404


class TestSendMessage:
    def test_send_to_nonexistent_conversation(self, client):
        resp = client.post("/api/chat/conversations/99999/messages", json={"content": "hi"})
        assert resp.status_code == 404

    def test_auto_title_on_first_message(self, client):
        conv = client.post("/api/chat/conversations", json={}).json()  # default title
        assert "id" in conv, f"Expected id in response, got: {conv}"
        with patch("app.services.chat_service.generate_chat_response", return_value=("ok", [])):
            resp = client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "我的第一个问题是什么呢"},
            )
        assert resp.status_code == 200, resp.text
        updated = client.get("/api/chat/conversations").json()
        my_conv = next(c for c in updated if c["id"] == conv["id"])
        assert my_conv["title"] != "New Conversation"