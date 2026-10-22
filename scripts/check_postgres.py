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
        # Durable adaptive lifecycle on the actual PostgreSQL schema, including
        # assistance, daily idempotency, source-based report staleness and ownership.
        import time
        from concurrent.futures import ThreadPoolExecutor
        from src.backend.diary_models import DailyDiary
        from sqlalchemy import func
        from src.backend.models import now
        mate = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"
        training = request(client, "POST", "/api/training/games", 201,
                           json={"focus": "mixed", "blind": True}).json()
        assert training["learning_source"] == "training" and "focus" not in training["training_context"]
        completed = []
        for _ in range(2):
            pending = request(client, "POST", "/api/games", 201, json={"mode": "computer", "fen": mate}).json()
            assert pending["difficulty_mode"] == "adaptive"
            request(client, "POST", "/api/hint", json={"game_id": pending["id"], "fen": mate, "level": 1})
            request(client, "POST", "/api/hint", json={"game_id": pending["id"], "fen": mate, "level": 2})
            completed.append(pending)
        def complete(pending):
            return request(client, "POST", f"/api/games/{pending['id']}/moves",
                           json={"move": "f7g7", "revision": 0}).json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            finished = list(pool.map(complete, completed))
        assert all(item["result"] == "1-0" for item in finished)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            statuses = [request(client, "GET", f"/api/games/{item['id']}/learning").json() for item in completed]
            if all(item["status"] == "completed" for item in statuses): break
            time.sleep(.1)
        assert all(item["status"] == "completed" for item in statuses), statuses
        assert all(item["evidence"]["independent_assessed"] == 0 for item in statuses)
        assert all(item["evidence"]["observations"][0]["assistance"] == "destination_revealed" for item in statuses)
        day = statuses[0]["completed_at"][:10]
        diary = request(client, "GET", f"/api/diary/days/{day}").json()
        assert diary["statistics"]["games"] == 2 and diary["statistics"]["assisted"] == 2
        assert diary["statistics"]["independent"] == 0
        regenerated = request(client, "POST", f"/api/diary/days/{day}/regenerate", json={}).json()
        assert regenerated["version"] == diary["version"]
        with SessionLocal() as db:
            assert db.scalar(select(func.count(DailyDiary.id)).where(DailyDiary.user_id == profile["id"])) == 1
        report = request(client, "POST", "/api/diary/reports", 201,
                         json={"start_date": day, "end_date": day}).json()
        assert report["statistics"]["games"] == 2 and not report["outdated"]
        assert request(client, "GET", f"/api/diary/reports/{report['id']}").json()["statistics"] == report["statistics"]
        activity = request(client, "GET", f"/api/diary/calendar?month={day[:7]}").json()
        assert activity["days"][0]["game_count"] == 2
        imported = request(client, "POST", "/api/games", 201,
                           json={"mode": "analysis", "pgn": '[Result "1-0"]\n\n1. e4 e5 1-0'}).json()
        assert imported["result"] == "1-0" and imported["completion_reason"] == "imported_result"
        assert "[Result \"1-0\"]" in request(client, "GET", f"/api/games/{imported['id']}/pgn").text
        resigning = request(client, "POST", "/api/games", 201, json={"mode": "computer"}).json()
        played = request(client, "POST", f"/api/games/{resigning['id']}/moves", json={"move": "e4", "revision": 0}).json()
        resigned = request(client, "POST", f"/api/games/{resigning['id']}/resign", json={"revision": played["revision"]}).json()
        assert resigned["result"] == "0-1" and resigned["status"] == "resignation"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            more = [request(client, "GET", f"/api/games/{item['id']}/learning").json() for item in (imported, resigned)]
            if all(item["status"] == "completed" for item in more): break
            time.sleep(.1)
        assert all(item["status"] == "completed" for item in more), more
        assert more[0]["evidence"]["counts"].get("unknown") == 1
        assert request(client, "GET", f"/api/diary/reports/{report['id']}").json()["outdated"]
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
        request(resumed, "GET", f"/api/diary/reports/{report['id']}", 404)
        assert request(resumed, "GET", "/api/diary/reports").json() == []
        assert request(resumed, "GET", f"/api/diary/calendar?month={day[:7]}").json()["days"] == []
        assert request(resumed, "GET", "/api/repertoire").json() == []
        assert request(resumed, "GET", "/api/progress").json()["attempts"] == 0
    engine.dispose()
    print("PostgreSQL API checks passed: profiles/isolation, saved legal gameplay, stale/CAS updates, real Stockfish, "
          "exploration, computer/undo, hints/attempts/progress, realistic training, both repertoires, durable coaching/resume, "
          "concurrent adaptive completion/assistance/automatic analysis/diary/idempotency/reports/isolation.")


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
            # Start from the previous shipped schema with actual legacy records.
            run([*alembic, "upgrade", "91b4e2a6c730"], env=os.environ.copy())
            from datetime import datetime, timezone
            import sqlalchemy as sa
            legacy_engine = sa.create_engine(database_url)
            metadata = sa.MetaData()
            metadata.reflect(bind=legacy_engine, only=["users", "games"])
            with legacy_engine.begin() as connection:
                connection.execute(metadata.tables["users"].insert().values(id="legacy-migration-user", name="migration-preservation", password_hash="", preferences={"difficulty": 4}, created_at=datetime.now(timezone.utc)))
                connection.execute(metadata.tables["games"].insert().values(id="legacy-migration-game", user_id="legacy-migration-user", initial_fen="8/8/8/8/8/8/5K2/7k w - - 0 1", moves=[], mode="training", player_color="white", difficulty=4, revision=0, created_at=datetime.now(timezone.utc)))
            run([*alembic, "upgrade", "head"], env=os.environ.copy())
            metadata = sa.MetaData()
            metadata.reflect(bind=legacy_engine, only=["users", "games"])
            with legacy_engine.begin() as connection:
                row = connection.execute(sa.select(metadata.tables["games"]).where(metadata.tables["games"].c.id == "legacy-migration-game")).mappings().one()
                assert row["moves"] == [] and row["difficulty"] == 4 and row["revision"] == 0
                assert row["assistance_tracked"] is False and row["difficulty_mode"] == "manual" and row["completed_at"] is None
                connection.execute(metadata.tables["users"].delete().where(metadata.tables["users"].c.id == "legacy-migration-user"))
            legacy_engine.dispose()
            print("PostgreSQL incremental migration preserved legacy games and unknown assistance.")
            for operation in (("check",), ("downgrade", "base"), ("upgrade", "head"), ("check",)):
                run([*alembic, *operation], env=os.environ.copy())
            print("PostgreSQL migrations passed: upgrade/check/downgrade-base/upgrade/check, with no schema drift.")
            api_checks()
        finally:
            if started:
                run([str(bindir / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])
    print("Stopped and removed the isolated PostgreSQL cluster; no existing service was used.")


if __name__ == "__main__":
    main()
