"""Deterministic TEI-compatible embedding stub for RAGFlow integration smoke.

This is NOT a semantic model and must never be used for production retrieval.
It exists only to validate the RAGFlow upload/parse/retrieval plumbing when a
real TEI model is unavailable. Vectors are normalized bag-of-token hashes.

Run in WSL/Linux:
    python3 scripts/tei_stub.py --port 8099
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSION = 1024


def _terms(text: str) -> list[str]:
    ascii_terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    return ascii_terms + [
        part[index:index + 2]
        for part in chinese
        for index in range(len(part) - 1)
    ]


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSION
    for term in _terms(text):
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSION
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/healthz", "/info"):
            self._send(200, {"status": "ok", "model": "tei-stub-1024",
                             "dimension": DIMENSION})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        if self.path == "/v1/embeddings":
            inputs = payload.get("input", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            data = [
                {"object": "embedding", "index": index, "embedding": embed(str(text))}
                for index, text in enumerate(inputs)
            ]
            self._send(200, {"object": "list", "data": data,
                             "model": payload.get("model", "tei-stub")})
            return
        if self.path in ("/embed", "/embeddings"):
            inputs = payload.get("inputs", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            self._send(200, [embed(str(text)) for text in inputs])
            return
        self._send(404, {"error": "not found"})

    def log_message(self, format, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"tei-stub listening on 0.0.0.0:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()