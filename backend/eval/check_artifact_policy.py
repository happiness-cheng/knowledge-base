"""镜像输入静态门禁；不读取、上传业务笔记，也不宣称实际镜像构建通过。"""
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    rules = set((root / ".dockerignore").read_text(encoding="utf-8").splitlines())
    required = {"**/.env*", "**/*.db*", "**/*.sqlite*", "**/*.safetensors",
                "backend/eval/fixtures", "backend/eval/reports", "backend/tests"}
    missing = required - rules
    if missing:
        raise SystemExit(f"missing artifact exclusions: {sorted(missing)}")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim" in dockerfile
    assert "KB_FRONTEND_DIST=/app/frontend/dist" in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert "alembic upgrade" not in dockerfile
    print("PASS: credentials/state/eval-data excluded; explicit frontend path; no automatic DDL")


if __name__ == "__main__":
    main()
