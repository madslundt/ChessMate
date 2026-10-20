#!/usr/bin/env python3
"""Verify deployed Chessmate through nginx, then verify durability after a stack restart.

Run seed, restart the Compose services without deleting volumes, then run resume.
The state file contains only disposable profile IDs and verification snapshots.
Resume removes its disposable profiles by default after verification.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

import chess
import chess.pgn
import httpx
import io


class Verification:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        split = urlsplit(self.base_url)
        self.origin = f"{split.scheme}://{split.netloc}"
        self.checks: list[str] = []
        self.created_profile_ids: list[str] = []

    def client(self, profile_id: str | None = None) -> httpx.Client:
        headers = {"Origin": self.origin}
        if profile_id:
            headers["X-Profile-ID"] = profile_id
        return httpx.Client(base_url=self.base_url, timeout=90, headers=headers, follow_redirects=False)

    def create_profile(self, client: httpx.Client, name: str) -> dict:
        profile = self.request(client, "POST", "/profiles", 201, json={"name": name}).json()
        self.created_profile_ids.append(profile["id"])
        client.headers["X-Profile-ID"] = profile["id"]
        return profile

    def cleanup(self, profile_ids: list[str]) -> None:
        with self.client() as client:
            for profile_id in profile_ids:
                response = client.delete("/api/profiles/" + profile_id)
                assert response.status_code in (204, 404), f"Could not remove disposable profile {profile_id}: {response.status_code}"
            remaining = {profile["id"] for profile in self.request(client, "GET", "/profiles").json()}
            assert not remaining.intersection(profile_ids), "Disposable verification profiles remain"
        self.record("disposable verification profiles and their owned data removed")

    def request(self, client: httpx.Client, method: str, path: str, expected: int = 200, **kwargs) -> httpx.Response:
        response = client.request(method, "/api" + path, **kwargs)
        assert response.status_code == expected, f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:1200]}"
        return response

    def record(self, name: str) -> None:
        self.checks.append(name)
        print(f"PASS {name}", flush=True)

    def race(self, client: httpx.Client, path: str, bodies: tuple[dict, dict]) -> dict:
        barrier = threading.Barrier(2)
        profile_id = client.headers["X-Profile-ID"]
        def post(body):
            with self.client(profile_id) as contender:
                barrier.wait(timeout=10)
                return contender.post("/api" + path, json=body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(post, bodies))
        assert sorted(r.status_code for r in responses) == [200, 409], [(r.status_code, r.text[:300]) for r in responses]
        return next(r.json() for r in responses if r.status_code == 200)

    def chat(self, client: httpx.Client, game: dict, question: str) -> tuple[dict, list[dict]]:
        response = self.request(client, "POST", "/coach", json={"game_id": game["id"], "revision": game["revision"],
            "fen": game["fen"], "question": question, "language": "en"})
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = []
        for frame in response.text.replace("\r\n", "\n").split("\n\n"):
            event = next((line[7:] for line in frame.splitlines() if line.startswith("event: ")), None)
            data = next((line[6:] for line in frame.splitlines() if line.startswith("data: ")), None)
            if event and data: frames.append((event, json.loads(data)))
        assert not any(event == "error" for event, _ in frames), frames
        assert any(event == "token" for event, _ in frames)
        done = next(data for event, data in frames if event == "done")
        assert done["fen"] == game["fen"] and done["revision"] == game["revision"]
        assert done["source"] in ("deterministic", "local_llm_verified") and done["text"]
        messages = self.request(client, "GET", f"/games/{game['id']}/conversation", params={"fen": game["fen"]}).json()["messages"]
        assert messages[-2]["role"] == "user" and messages[-2]["content"] == question
        assert messages[-1]["role"] == "assistant" and messages[-1]["content"] == done["text"]
        assert all(message["fen"] == game["fen"] for message in messages)
        return done, messages

    def seed(self) -> dict:
        suffix = secrets.token_hex(6)
        with self.client() as client:
            health = self.request(client, "GET", "/health").json()
            assert health["status"] == "ok" and health["engine"] == "available"
            self.request(client, "GET", "/games", 400)
            self.record("nginx HTTP health, Stockfish availability, profile selection required")
            user = self.create_profile(client, f"compose_{suffix}")
            assert "password" not in user and "password_hash" not in user
            assert any(profile["id"] == user["id"] for profile in self.request(client, "GET", "/profiles").json())
            self.request(client, "POST", "/games", 403, json={}, headers={"Origin": "https://untrusted.invalid"})
            self.request(client, "POST", "/games", 415, content="{}", headers={"Content-Type": "text/plain"})
            self.record("password-free profile selection, proxy-origin and JSON CSRF guards")
            preferences = self.request(client, "PATCH", "/settings", json={"theme": "dark", "language": "da", "coach_language": "en",
                "show_evaluation": True, "show_pv": True, "show_alternatives": True, "hide_best_moves": True,
                "analysis_time_ms": 100, "auto_computer": False}).json()
            game = self.request(client, "POST", "/games", 201, json={"mode": "training", "difficulty": 5, "player_color": "white"}).json()
            url = f"/games/{game['id']}"
            self.request(client, "POST", url + "/moves", 422, json={"move": "e2e5", "revision": 0})
            game = self.race(client, url + "/moves", ({"move": "e4", "revision": 0}, {"move": "d4", "revision": 0}))
            assert game["revision"] == 1 and len(game["moves"]) == 1
            feedback = game["moves"][0]["feedback"]
            assert feedback["fen"] == chess.STARTING_FEN and feedback["move"] == game["moves"][0]["uci"]
            assert feedback["confidence"] != "unavailable" and feedback["played"]["uci"] == feedback["move"]
            self.record("simultaneous real HTTP player requests: one commit, one409; legal move and root-grounded Stockfish feedback")
            done, first_messages = self.chat(client, game, "Which center squares do my pieces control?")
            assert "It is Black's turn" in done["text"] and "You are playing White" in done["text"]
            if health["llm"] == "offline_fallback": assert done["source"] == "deterministic"
            first_chat = {"fen": game["fen"], "messages": first_messages}
            self.record("SSE fallback, paused-computer learner perspective, exact-FEN persisted conversation")
            analysis = self.request(client, "POST", "/analysis", json={"fen": game["fen"], "time_ms": 150, "candidates": 3}).json()
            assert analysis["source"] == "stockfish" and len(analysis["candidates"]) == 3 and analysis["perspective"] == "black"
            board = chess.Board(game["fen"])
            for candidate in analysis["candidates"]:
                move = chess.Move.from_uci(candidate["uci"])
                assert move in board.legal_moves and board.san(move) == candidate["san"]
                assert candidate["white_cp"] == -candidate["cp"]
                replay = board.copy()
                for san in candidate["pv"]: replay.push_san(san)
            exploration = self.request(client, "POST", "/analysis", json={"fen": game["fen"], "moves": [analysis["candidates"][0]["uci"]], "time_ms": 50}).json()
            assert exploration["fen"] != game["fen"]
            assert self.request(client, "GET", url).json()["fen"] == game["fen"]
            self.record("real Stockfish top-three MultiPV, legal SAN/UCI variations, Black POV, isolated exploration")
            game = self.race(client, url + "/computer", ({"revision": 1}, {"revision": 1}))
            assert game["revision"] == 2 and len(game["moves"]) == 2
            assert chess.Move.from_uci(game["moves"][-1]["uci"]) in board.legal_moves
            self.request(client, "POST", url + "/undo", 409, json={"revision": 1})
            game = self.request(client, "POST", url + "/undo", json={"revision": 2}).json()
            assert game["revision"] == 3 and game["moves"] == []
            game = self.request(client, "POST", url + "/moves", json={"move": "Nf3", "revision": 3}).json()
            game = self.request(client, "POST", url + "/computer", json={"revision": 4}).json()
            assert game["revision"] == 5 and len(game["moves"]) == 2
            self.record("simultaneous computer requests: one commit, one409; stale undo rejected; training undo and resumed gameplay")
            final_chat, final_messages = self.chat(client, game, "Why was my last move good or bad?")
            assert "Nf3" in final_chat["text"]
            review = self.request(client, "GET", url + "/review").json()
            assert review["game_id"] == game["id"] and review["revision"] == 5 and review["summary"]
            assert isinstance(review["mistakes"], list) and isinstance(review["positives"], list)
            self.record("previous-move explanation and saved post-game review through the proxy")
            imported = self.request(client, "POST", "/games", 201, json={"mode": "analysis", "pgn": "1. f3 e5 2. g4 Qh4# 0-1"}).json()
            assert imported["status"] == "checkmate" and imported["result"] == "0-1"
            pgn = self.request(client, "GET", f"/games/{imported['id']}/pgn").text
            parsed = chess.pgn.read_game(io.StringIO(pgn))
            assert parsed and parsed.end().board().fen() == imported["fen"]
            roundtrip = self.request(client, "POST", "/games", 201, json={"mode": "analysis", "pgn": pgn}).json()
            assert roundtrip["fen"] == imported["fen"]
            promotion = self.request(client, "POST", "/games", 201, json={"mode": "analysis", "fen": "7k/P7/8/8/8/8/8/7K w - - 0 1"}).json()
            promotion = self.request(client, "POST", f"/games/{promotion['id']}/moves", json={"move": "a7a8n", "revision": 0}).json()
            assert promotion["status"] == "insufficient_material" and promotion["result"] == "1/2-1/2"
            assert "a8=N" in self.request(client, "GET", f"/games/{promotion['id']}/pgn").text
            self.record("PGN import/export/roundtrip/checkmate and FEN underpromotion/draw")
            public_ids = [item["id"] for item in self.request(client, "GET", "/exercises").json()]
            assert len(public_ids) >= 48 and len(public_ids) == len(set(public_ids))
            with self.client() as other:
                other_user = self.create_profile(other, f"compose_other_{suffix}")
                assert other_user["id"] != user["id"]
                for path in (url, url + "/pgn", url + "/review", url + "/conversation"):
                    self.request(other, "GET", path, 404)
                self.request(other, "POST", "/coach", 404, json={"fen": game["fen"], "game_id": game["id"], "revision": 5, "question": "Explain"})
                assert self.request(other, "GET", "/games").json() == []
                assert self.request(other, "GET", "/settings").json()["theme"] == "light"
                self.request(other, "DELETE", f"/profiles/{other_user['id']}", 204)
                self.request(other, "GET", "/games", 404)
                assert all(profile["id"] != other_user["id"] for profile in self.request(other, "GET", "/profiles").json())
            self.record("cross-profile game/review/PGN/conversation isolation and removed-profile rejection")
            snapshots = [{key: item[key] for key in ("id", "fen", "initial_fen", "revision", "moves", "status", "result")}
                         for item in (game, imported, roundtrip, promotion)]
            return {"version": 2, "base_url": self.base_url, "profile_ids": self.created_profile_ids,
                    "profile_id": user["id"], "preferences": preferences, "games": snapshots,
                    "conversations": [first_chat, {"fen": game["fen"], "messages": final_messages}],
                    "conversation_game_id": game["id"], "review": review, "public_exercise_ids": public_ids,
                    "seed_checks": self.checks, "coaching_source": done["source"]}

    def resume(self, saved: dict) -> None:
        assert saved["version"] == 2 and saved["base_url"] == self.base_url
        with self.client(saved["profile_id"]) as client:
            assert self.request(client, "GET", "/health").json()["status"] == "ok"
            assert any(profile["id"] == saved["profile_id"] for profile in self.request(client, "GET", "/profiles").json())
            self.record("same persisted profile remains selectable")
            assert self.request(client, "GET", "/settings").json() == saved["preferences"]
            for expected in saved["games"]:
                actual = self.request(client, "GET", f"/games/{expected['id']}").json()
                assert {key: actual[key] for key in expected} == expected
            self.record("exact games, revisions, move evidence, imports, promotion and preferences persisted")
            url = f"/games/{saved['conversation_game_id']}"
            for conversation in saved["conversations"]:
                actual = self.request(client, "GET", url + "/conversation", params={"fen": conversation["fen"]}).json()["messages"]
                assert actual == conversation["messages"]
            assert self.request(client, "GET", url + "/review").json() == saved["review"]
            public_ids = [item["id"] for item in self.request(client, "GET", "/exercises").json()]
            assert public_ids == saved["public_exercise_ids"]
            self.record("exact-FEN conversations/review persisted and curriculum seeds remain idempotent")
            analysis = self.request(client, "POST", "/analysis", json={"fen": saved["games"][0]["fen"], "time_ms": 100}).json()
            assert analysis["source"] == "stockfish" and len(analysis["candidates"]) == 3
            client.headers.pop("X-Profile-ID")
            self.request(client, "GET", url, 400)
            client.headers["X-Profile-ID"] = saved["profile_id"]
            assert self.request(client, "GET", url).json()["revision"] == saved["games"][0]["revision"]
            self.record("Stockfish is available; profile reselection restores saved game access")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("seed", "resume", "cleanup"))
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--state", type=Path, default=Path(__file__).parent / ".http-state.json")
    parser.add_argument("--keep-state", action="store_true", help="Keep the verification state file after resume")
    parser.add_argument("--keep-profiles", action="store_true", help="Keep disposable profiles after resume for inspection")
    args = parser.parse_args()
    check = Verification(args.base_url)
    if args.phase == "seed":
        if args.state.exists(): parser.error("State already exists; use resume or choose a new --state path")
        try:
            state = check.seed()
            args.state.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output: json.dump(state, output)
        except BaseException:
            check.cleanup(check.created_profile_ids)
            raise
        print(f"Seed checks passed. Private restart state saved to {args.state}. Restart the full stack without deleting volumes, then run resume.")
    else:
        saved = json.loads(args.state.read_text())
        assert saved["version"] == 2 and saved["base_url"] == check.base_url
        if args.phase == "cleanup":
            check.cleanup(saved["profile_ids"])
        else:
            check.resume(saved)
            if not args.keep_profiles:
                check.cleanup(saved["profile_ids"])
        if not args.keep_state:
            args.state.unlink()
        print("Verification and requested cleanup passed.")
    print(json.dumps({"phase": args.phase, "status": "passed", "checks": check.checks}))


if __name__ == "__main__":
    main()
