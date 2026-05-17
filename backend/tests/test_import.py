"""Tests for /api/import endpoints."""
import io


class TestImportText:
    def test_import_plain_text(self, client):
        resp = client.post("/api/import/text", json={
            "title": "导入测试",
            "content": "# 标题一\n这是内容\n## 标题二\n更多内容",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] >= 1

    def test_import_empty_content(self, client):
        resp = client.post("/api/import/text", json={"content": ""})
        assert resp.status_code == 400

    def test_import_creates_nodes(self, client):
        client.post("/api/import/text", json={
            "title": "Test",
            "content": "# Chapter 1\nContent 1\n# Chapter 2\nContent 2",
        })
        nodes = client.get("/api/nodes").json()
        assert len(nodes) >= 1


class TestImportFile:
    def test_import_md_file(self, client):
        md_content = b"# Heading\nSome markdown content"
        resp = client.post(
            "/api/import/file",
            files={"file": ("test.md", io.BytesIO(md_content), "text/markdown")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] >= 1

    def test_import_txt_file(self, client):
        txt_content = b"Plain text content for testing"
        resp = client.post(
            "/api/import/file",
            files={"file": ("notes.txt", io.BytesIO(txt_content), "text/plain")},
        )
        assert resp.status_code == 200

    def test_import_unsupported_type(self, client):
        resp = client.post(
            "/api/import/file",
            files={"file": ("image.png", b"\x89PNG", "image/png")},
        )
        assert resp.status_code == 400


class TestImportBatch:
    def test_import_multiple_files(self, client):
        files = [
            ("files", ("a.md", io.BytesIO(b"# A\nContent A"), "text/markdown")),
            ("files", ("b.md", io.BytesIO(b"# B\nContent B"), "text/markdown")),
        ]
        resp = client.post("/api/import/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["imported"]) == 2
