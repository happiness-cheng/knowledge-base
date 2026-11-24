"""Minimal TEI/OpenAI-compatible server for a locally cached BGE model.

Development utility for RAGFlow smoke. It is not a production embedding
service: no auth, no batching limits, no request queue. Load the model once
and serve normalized vectors.

    python -m scripts.bge_server --port 8099
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sentence_transformers import SentenceTransformer


class Handler(BaseHTTPRequestHandler):
    model: SentenceTransformer
    model_name = "BAAI/bge-large-zh-v1.5"

    def _send(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/healthz", "/info"):
            self._send(200, {"status": "ok", "model": self.model_name,
                             "dimension": int(self.model.get_sentence_embedding_dimension())})
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
            vectors = self.model.encode(
                [str(text) for text in inputs], normalize_embeddings=True,
                batch_size=16, show_progress_bar=False,
            )
            self._send(200, {
                "object": "list",
                "model": payload.get("model", self.model_name),
                "data": [
                    {"object": "embedding", "index": index,
                     "embedding": [float(value) for value in vector]}
                    for index, vector in enumerate(vectors)
                ],
            })
            return
        if self.path in ("/embed", "/embeddings"):
            inputs = payload.get("inputs", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            vectors = self.model.encode(
                [str(text) for text in inputs], normalize_embeddings=True,
                batch_size=16, show_progress_bar=False,
            )
            self._send(200, [[float(value) for value in vector] for vector in vectors])
            return
        self._send(404, {"error": "not found"})

    def log_message(self, format, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--model", default="BAAI/bge-large-zh-v1.5")
    args = parser.parse_args()
    Handler.model = SentenceTransformer(
        args.model, local_files_only=True, device="cpu",
    )
    Handler.model_name = args.model
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"bge-server listening on {args.host}:{args.port} model={args.model}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()