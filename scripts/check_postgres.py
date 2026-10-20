#!/usr/bin/env python3
"""Opt-in PostgreSQL integration check using an isolated, disposable local cluster.

Run with the project virtualenv. Requires initdb/pg_ctl/createdb (PostgreSQL 17)
and Stockfish. Never connects to an existing database or opens a TCP listener.
"""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"{shlex.join(command)}\n{result.stdout}\n{result.stderr}")


def api_checks() -> None:
    import chess
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from src.backend.database import SessionLocal, engine
    from src.backend.exercises import read_library
    from src.backend.games import append_move, board_for, commit_event
    from src.backend.main import app
    from src.backend.models import Game, GameEvent

    def request(client, method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, f"{method} {path}: {response.status_code} {response.text}"
        return response

    with TestClient(app) as client:
        assert request(client, "GET", "/api/health").json()["engine"] == "available"
        request(client, "GET", "/api/games", 400)
        profile = request(client, "POST", "/api/profiles", 201, json={"name": "postgres-verification"}).json()
        client.headers["X-Profile-ID"] = profile["id"]
        request(client, "PATCH", "/api/settings", json={"show_evaluation": True, "show_pv": True,
                "show_alternatives": True, "hide_best_moves": False, "analysis_time_ms": 100})
        game = request(client, "POST", "/api/games", 201,
                       json={"mode": "training", "difficulty": 5, "player_color": "white"}).json()
        url = f"/api/games/{game['id']}"
        request(client, "POST", url + "/moves", 422, json={"move": "e2e5", "revision": 0})
        moved = request(client, "POST", url + "/moves", json={"move": "e4", "revision": 0}).json()
        assert moved["revision"] == 1 and moved["moves"][0]["san"] == "e4"
        assert moved["moves"][0]["feedback"]["confidence"] != "unavailable"
        assert request(client, "GET", url).json()["fen"] == moved["fen"]
        request(client, "POST", url + "/moves", 409, json={"move": "Nf3", "revision": 0})
        computer = request(client, "POST", url + "/computer", json={"revision": 1}).json()
        board = chess.Board(moved["fen"])
        assert chess.Move.from_uci(computer["moves"][-1]["uci"]) in board.legal_moves
        undone = request(client, "POST", url + "/undo", json={"revision": 2}).json()
        assert undone["revision"] == 3 and undone["moves"] == []
        analysis = request(client, "POST", "/api/analysis", json={"fen": undone["fen"],
                           "moves": ["e4"], "time_ms": 100, "candidates": 3}).json()
        assert analysis["source"] == "stockfish" and len(analysis["candidates"]) == 3
        assert analysis["fen"] != undone["fen"]
        assert request(client, "GET", url).json()["fen"] == undone["fen"]

        # Independent SQLAlchemy sessions exercise PostgreSQL's real update/CAS path.
        race = request(client, "POST", "/api/games", 201, json={"mode": "analysis"}).json()
        with SessionLocal() as first, SessionLocal() as second:
            a, b = first.get(Game, race["id"]), second.get(Game, race["id"])
            for instance, text in ((a, "e4"), (b, "d4")):
                root = board_for(instance)
                append_move(instance, root, root.parse_san(text), None, "player")
            commit_event(first, a, "move", {"san": "e4"})
            try:
                commit_event(second, b, "move", {"san": "d4"})
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Concurrent stale PostgreSQL update was accepted")
            events = second.scalars(select(GameEvent).where(GameEvent.game_id == race["id"],
                                                            GameEvent.kind == "move")).all()
            assert len(events) == 1

        exercises = request(client, "GET", "/api/exercises").json()
        assert len(exercises) == len(read_library()) and all("solution" not in entry for entry in exercises)
        hint = request(client, "POST", "/api/exercises/opening-01/hint", json={"level": 1}).json()
        assert "move" not in hint
        attempt = request(client, "POST", "/api/exercises/opening-01/attempt",
                          json={"moves": ["e4"], "hint_level": 0}).json()
        assert attempt["correct"] and attempt["complete"] and attempt["hint_level"] == 1
        progress = request(client, "GET", "/api/progress").json()
        assert progress["attempts"] == 1 and progress["correct"] == 1 and progress["hints_used"] == 1
        assert request(client, "POST", "/api/training/sessions", json={"kind": "daily"}).json()["exercises"]

        saved_lines = []
        for color, moves in (("white", ["e4", "e5", "Nf3", "Nc6", "Bc4"]),
                             ("black", ["d4", "Nf6", "c4", "e6"])):
            line = request(client, "POST", "/api/repertoire", 201,
                           json={"name": f"PostgreSQL {color}", "color": color, "moves": moves}).json()
            practice = request(client, "POST", f"/api/repertoire/{line['id']}/practice", json={}).json()
            assert practice["exercises"] and all("solution" not in x for x in practice["exercises"])
            saved_lines.append(line["id"])

        question = {"fen": undone["fen"], "game_id": game["id"], "revision": 3,
                    "question": "What should I focus on?"}
        chat = request(client, "POST", "/api/coach", json=question)
        assert "event: token" in chat.text and "event: done" in chat.text and "deterministic" in chat.text
        conversation = request(client, "GET", url + "/conversation").json()["messages"]
        assert [m["role"] for m in conversation] == ["user", "assistant"]
        del client.headers["X-Profile-ID"]
        request(client, "GET", url, 400)

    # New lifespan/client resumes the same profile and PostgreSQL data.
    with TestClient(app) as resumed:
        resumed.headers["X-Profile-ID"] = profile["id"]
        assert request(resumed, "GET", url).json()["revision"] == 3
        assert len(request(resumed, "GET", url + "/conversation").json()["messages"]) == 2
        assert request(resumed, "GET", "/api/progress").json()["correct"] == 1
        assert {x["id"] for x in request(resumed, "GET", "/api/repertoire").json()} == set(saved_lines)
        other = request(resumed, "POST", "/api/profiles", 201,
                        json={"name": "postgres-other-profile"}).json()
        resumed.headers["X-Profile-ID"] = other["id"]
        request(resumed, "GET", url, 404)
        assert request(resumed, "GET", "/api/repertoire").json() == []
        assert request(resumed, "GET", "/api/progress").json()["attempts"] == 0
    engine.dispose()
    print("PostgreSQL API checks passed: profiles/isolation, saved legal gameplay, stale/CAS updates, real Stockfish, "
          "exploration, computer/undo, hints/attempts/progress, training, both repertoires, durable coaching/resume.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindir", type=Path, help="Directory containing PostgreSQL binaries")
    parser.add_argument("--port", type=int, default=55437)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    binary = shutil.which("initdb")
    bindir = args.bindir or (Path(binary).parent if binary else Path("/opt/homebrew/opt/postgresql@17/bin"))
    for tool in ("initdb", "pg_ctl", "createdb"):
        if not (bindir / tool).is_file():
            parser.error(f"Missing {tool}; install PostgreSQL and pass --bindir")
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix=".postgres-check-", dir=ROOT / "tests") as directory:
        temporary = Path(directory)
        data, socket = temporary / "data", temporary / "socket"
        socket.mkdir(mode=0o700)
        run([str(bindir / "initdb"), "-D", str(data), "--auth-local=trust", "--auth-host=reject",
             "--no-locale", "--encoding=UTF8"])
        options = shlex.join(["-F", "-h", "", "-k", str(socket), "-p", str(args.port)])
        started = False
        try:
            run([str(bindir / "pg_ctl"), "-D", str(data), "-l", str(temporary / "postgres.log"),
                 "-o", options, "-w", "start"])
            started = True
            run([str(bindir / "createdb"), "-h", str(socket), "-p", str(args.port), "chessmate_verification"])
            database_url = (f"postgresql+psycopg://{quote(getpass.getuser(), safe='')}@/chessmate_verification"
                            f"?host={quote(str(socket), safe='')}&port={args.port}")
            os.environ.update(DATABASE_URL=database_url, LLM_BASE_URL="", LLM_MODEL="", LLM_API_KEY="", COOKIE_SECURE="false")
            alembic = [sys.executable, "-m", "alembic", "-c", "src/backend/alembic.ini"]
            for operation in (("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head"), ("check",)):
                run([*alembic, *operation], env=os.environ.copy())
            print("PostgreSQL migrations passed: upgrade/check/downgrade-base/upgrade/check, with no schema drift.")
            api_checks()
        finally:
            if started:
                run([str(bindir / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])
    print("Stopped and removed the isolated PostgreSQL cluster; no existing service was used.")


if __name__ == "__main__":
    main()
