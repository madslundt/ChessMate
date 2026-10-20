"""A test-only OpenAI-compatible SSE server. Never used by the product deployment."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import chess

records = []
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not log user prompts, request context, or headers.

    def do_GET(self):
        if self.path != "/results":
            self.send_error(404)
            return
        with lock: body = json.dumps(records).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            assert self.path == "/v1/chat/completions"
            assert self.headers.get("Authorization") == "Bearer fixture-only-test-key"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload["model"] == "protocol-fixture" and payload["stream"] is True
            assert payload["messages"][0]["role"] == "system"
            supplied = json.loads(payload["messages"][1]["content"])
            context, catalog = supplied["verified_context"], supplied["statement_catalog"]
            board = chess.Board(context["fen"])
            assert board.is_valid() and context["analysis"]["fen"] == board.fen()
            assert context["learner_color"] == context["side_to_move"] == "white"
            legal = {move.uci() for move in board.legal_moves}
            assert {move["uci"] for move in context["legal_moves"]} == legal
            candidate = context["requested_candidates"][0]
            assert candidate["uci"] == "g1f3" and candidate["san"] == "Nf3"
            replay = board.copy()
            for value in candidate["pv_uci"]:
                move = chess.Move.from_uci(value)
                assert move in replay.legal_moves
                replay.push(move)
            assert "candidate_0" in catalog and "line_0" in catalog
            kind = next(kind for kind in ("valid", "malformed", "illegal", "timeout") if f"fixture_{kind}" in context["question"])
            with lock:
                records.append({"kind": kind, "context_verified": True, "fen": board.fen(),
                                "candidate": candidate["uci"], "pv_length": len(candidate["pv_uci"])})
            selection = {"fact_ids": ["candidate_0", "line_0"], "candidate_uci": candidate["uci"],
                         "pv_uci": candidate["pv_uci"][:3], "tone": "explain"}
            if kind == "timeout": time.sleep(3)
            if kind == "illegal": selection.update(candidate_uci="e2e5", pv_uci=["e2e5"])
            completion = "not valid JSON" if kind == "malformed" else json.dumps(selection)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for fragment in (completion[:12], completion[12:]):
                item = {"choices": [{"delta": {"content": fragment}}]}
                self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # The timeout test deliberately disconnects before the fixture responds.
        except Exception:
            with lock: records.append({"kind": "invalid_context", "context_verified": False})
            self.send_error(400, "Fixture rejected the supplied context")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
