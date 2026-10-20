import chess


def start(client, **fields):
    response = client.post("/api/games", json=fields)
    assert response.status_code == 201, response.text
    return response.json()


def test_auth_ownership_and_revocation(signed):
    game = start(signed)
    assert signed.post("/api/auth/logout", json={}).status_code == 200
    assert signed.get("/api/games").status_code == 401
    signed.post("/api/auth/register", json={"name": "other", "password": "other-password"})
    assert signed.get("/api/games/" + game["id"]).status_code == 404


def test_game_revision_legal_moves_and_computer(signed):
    game = start(signed)
    url = f"/api/games/{game['id']}"
    assert signed.post(url + "/moves", json={"move": "e2e5", "revision": 0}).status_code == 422
    response = signed.post(url + "/moves", json={"move": "e4", "revision": 0})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["revision"] == 1 and state["moves"][-1]["san"] == "e4"
    feedback = state["moves"][-1]["feedback"]
    assert feedback["classification"] and "best" not in feedback
    assert "pv" not in feedback.get("played", {})
    assert signed.post(url + "/moves", json={"move": "Nf3", "revision": 0}).status_code == 409
    assert signed.post(url + "/moves", json={"move": "e5", "revision": 1}).status_code == 409
    computer = signed.post(url + "/computer", json={"revision": 1})
    assert computer.status_code == 200, computer.text
    assert computer.json()["revision"] == 2
    undo = signed.post(url + "/undo", json={"revision": 2})
    assert undo.json()["moves"] == [] and undo.json()["revision"] == 3


def test_pgn_fen_and_independent_exploration(signed):
    game = start(signed, mode="analysis", pgn='[Event "Test"]\n\n1. e4 e5 2. Nf3 *')
    url = "/api/games/" + game["id"]
    assert [m["san"] for m in game["moves"]] == ["e4", "e5", "Nf3"]
    assert "1. e4 e5 2. Nf3" in signed.get(url + "/pgn").text
    result = signed.post("/api/analysis", json={"fen": game["fen"], "moves": ["Nc6"], "time_ms": 50})
    assert result.status_code == 200, result.text
    assert result.json()["fen"] != game["fen"]
    actual = signed.get(url).json()
    assert actual["fen"] == game["fen"] and actual["revision"] == game["revision"]
    imported = start(signed, mode="analysis", fen="7k/P7/8/8/8/8/8/K7 w - - 0 1")
    assert imported["initial_fen"].startswith("7k/P7")


def test_settings_validate_and_persist(signed):
    assert signed.patch("/api/settings", json={"feedback": "detailed", "auto_computer": True}).status_code == 200
    assert signed.get("/api/settings").json()["auto_computer"] is True
    assert signed.patch("/api/settings", json={"llm_api_key": "secret"}).status_code == 422
    assert signed.patch("/api/settings", json={"analysis_time_ms": 99999}).status_code == 422


def test_csrf_and_validation(signed):
    assert signed.post("/api/games", json={}, headers={"origin": "https://evil.example"}).status_code == 403
    assert signed.post("/api/games", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert signed.post("/api/analysis", json={"fen": "bad"}).status_code == 422


def test_hint_levels_do_not_reveal_candidates_early(signed):
    for level in range(1, 5):
        response = signed.post("/api/hint", json={"fen": chess.STARTING_FEN, "level": level})
        assert response.status_code == 200, response.text
        assert bool(response.json().get("candidates")) == (level == 4)


def test_coach_correct_board_offline_and_stale(signed):
    game = start(signed)
    request = {"fen": game["fen"], "game_id": game["id"], "revision": 0, "question": "What should I focus on?"}
    response = signed.post("/api/coach", json=request)
    assert response.status_code == 200, response.text
    assert "event: token" in response.text and "event: done" in response.text
    assert "deterministic" in response.text
    assert signed.post("/api/coach", json={**request, "revision": 2}).status_code == 409
    assert signed.post("/api/coach", json={**request, "fen": "7k/P7/8/8/8/8/8/K7 w - - 0 1"}).status_code == 409
    assert signed.post("/api/coach", json={**request, "fen": "7k/P7/8/8/8/8/8/K7 w - - 0 1", "explore": True}).status_code == 200


def test_concurrent_revision_compare_and_swap_keeps_one_event(signed):
    from fastapi import HTTPException
    from sqlalchemy import select
    import pytest
    import src.backend.main as main
    from src.backend.models import Game, GameEvent
    from src.backend.games import append_move, board_for, commit_event
    game = start(signed, mode="analysis")
    with main.SessionLocal() as first, main.SessionLocal() as second:
        first_game, second_game = first.get(Game, game["id"]), second.get(Game, game["id"])
        for session, item, san in ((first, first_game, "e4"), (second, second_game, "d4")):
            board = board_for(item)
            append_move(item, board, board.parse_san(san), None, "player")
        commit_event(first, first_game, "move", {"san": "e4"})
        with pytest.raises(HTTPException) as error:
            commit_event(second, second_game, "move", {"san": "d4"})
        assert error.value.status_code == 409
        events = second.scalars(select(GameEvent).where(GameEvent.game_id == game["id"], GameEvent.kind == "move")).all()
        assert len(events) == 1
    assert signed.get(f"/api/games/{game['id']}").json()["moves"][0]["san"] == "e4"


def test_engine_failure_still_saves_legal_player_move(signed, monkeypatch):
    from src.backend.engine import EngineUnavailable, engine_service
    def failed(*args, **kwargs): raise EngineUnavailable("offline")
    monkeypatch.setattr(engine_service, "grade", failed)
    game = start(signed)
    response = signed.post(f"/api/games/{game['id']}/moves", json={"move": "e4", "revision": 0})
    assert response.status_code == 200
    assert response.json()["moves"][0]["feedback"]["confidence"] == "unavailable"


def test_historical_coaching_context_never_contains_future_moves(signed, monkeypatch):
    from src.backend.coach import coach_service
    game = start(signed, mode="analysis", pgn="1. e4 e5 2. Nf3 Nc6 *")
    captured = []
    original = coach_service.context
    def observe(*args, **kwargs):
        context = original(*args, **kwargs)
        captured.append(context)
        return context
    monkeypatch.setattr(coach_service, "context", observe)
    fen = game["moves"][0]["fen"]
    response = signed.post("/api/coach", json={"fen": fen, "game_id": game["id"], "revision": 0, "question": "What was my last move?"})
    assert response.status_code == 200
    context = captured[0]
    assert context["game"]["selected_ply"] == 1
    assert [m["san"] for m in context["game"]["recent_moves"]] == ["e4"]
    assert context["game"]["last_move"]["san"] == "e4"
    assert context["fen"] == fen


def test_previous_move_explanation_and_persisted_conversation(signed):
    game = start(signed)
    game = signed.post(f"/api/games/{game['id']}/moves", json={"move": "e4", "revision": 0}).json()
    response = signed.post("/api/coach", json={"fen": game["fen"], "game_id": game["id"], "revision": 1, "question": "Why was my last move bad?"})
    assert response.status_code == 200
    assert "earlier decision e4" in response.text and "original position" in response.text
    conversation = signed.get(f"/api/games/{game['id']}/conversation", params={"fen": game["fen"]}).json()
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant"]
    assert conversation["messages"][0]["content"] == "Why was my last move bad?"
    assert all(m["fen"] == game["fen"] for m in conversation["messages"])
    empty = signed.get(f"/api/games/{game['id']}/conversation", params={"fen": chess.STARTING_FEN}).json()
    assert empty["messages"] == []


def test_analysis_uses_coaching_language_and_feedback_filters_recursively(signed):
    signed.patch("/api/settings", json={"coach_language": "da"})
    response = signed.post("/api/analysis", json={"fen": chess.STARTING_FEN, "time_ms": 50})
    assert response.status_code == 200
    assert all("This " not in c["explanation"] and "Compare " not in c["explanation"] for c in response.json()["candidates"])
    game = start(signed)
    game = signed.post(f"/api/games/{game['id']}/moves", json={"move": "Nf3", "revision": 0}).json()
    import json
    evidence = json.dumps(game["moves"][0]["feedback"])
    for hidden in ('"pv"', '"pv_uci"', '"legal_reply_captures"', '"cp"', '"best"', '"alternatives"'):
        assert hidden not in evidence


def test_paused_computer_turn_coach_keeps_white_learner_identity(signed):
    import json
    game = start(signed)
    game = signed.post(f"/api/games/{game['id']}/moves", json={"move": "e4", "revision": 0}).json()
    response = signed.post("/api/coach", json={"fen": game["fen"], "game_id": game["id"], "revision": 1,
        "question": "Which center squares do my pieces control?"})
    assert response.status_code == 200
    done = next(frame for frame in response.text.split("\n\n") if frame.startswith("event: done"))
    text = json.loads(done.split("data: ", 1)[1])["text"]
    assert "It is Black's turn" in text and "You are playing White" in text
    assert "Your pieces geometrically control these central squares: d5." in text


def test_computer_replies_default_on_and_saved_pause_survives_login(client):
    credentials = {"name": "automatic-replies", "password": "automatic-replies-password"}
    registered = client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201
    assert registered.json()["preferences"]["auto_computer"] is True
    assert client.get("/api/settings").json()["auto_computer"] is True

    paused = client.patch("/api/settings", json={"auto_computer": False})
    assert paused.status_code == 200 and paused.json()["auto_computer"] is False
    updated = client.patch("/api/settings", json={"feedback": "detailed"})
    assert updated.status_code == 200 and updated.json()["auto_computer"] is False

    assert client.post("/api/auth/logout", json={}).status_code == 200
    signed_in = client.post("/api/auth/login", json=credentials)
    assert signed_in.status_code == 200
    assert signed_in.json()["preferences"]["auto_computer"] is False
    assert client.get("/api/settings").json()["auto_computer"] is False
