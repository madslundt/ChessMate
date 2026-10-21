import chess
import pytest


def start(client, **fields):
    response = client.post("/api/games", json=fields)
    assert response.status_code == 201, response.text
    return response.json()


def test_profile_selection_and_game_ownership(signed):
    original_id = signed.headers.pop("X-Profile-ID")
    assert signed.get("/api/games").status_code == 400
    signed.headers["X-Profile-ID"] = original_id
    game = start(signed)
    other = signed.post("/api/profiles", json={"name": "other"})
    assert other.status_code == 201
    signed.headers["X-Profile-ID"] = other.json()["id"]
    assert signed.get("/api/games").json() == []
    assert signed.get("/api/games/" + game["id"]).status_code == 404
    signed.headers["X-Profile-ID"] = original_id
    assert signed.get("/api/games/" + game["id"]).status_code == 200


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


@pytest.mark.parametrize("player_color,pgn,remaining", [
    ("white", "1. e4 e5 2. Nf3 *", ["e4", "e5"]),
    ("white", "1. e4 e5 2. Nf3 Nc6 *", ["e4", "e5"]),
    ("black", "1. e4 e5 2. Nf3 Nc6 *", ["e4", "e5", "Nf3"]),
    ("black", "1. e4 e5 2. Nf3 Nc6 3. Bb5 *", ["e4", "e5", "Nf3"]),
])
def test_training_undo_returns_to_before_players_last_move(signed, player_color, pgn, remaining):
    game = start(signed, mode="training", player_color=player_color, pgn=pgn)
    url = f"/api/games/{game['id']}"
    response = signed.post(url + "/undo", json={"revision": game["revision"]})
    assert response.status_code == 200, response.text
    undone = response.json()
    assert [move["san"] for move in undone["moves"]] == remaining
    assert undone["fen"] == game["moves"][len(remaining) - 1]["fen"]
    assert undone["turn"] == player_color
    persisted = signed.get(url).json()
    assert persisted["moves"] == undone["moves"] and persisted["can_redo"]
    response = signed.post(url + "/redo", json={"revision": undone["revision"]})
    assert response.status_code == 200, response.text
    restored = response.json()
    assert [move["uci"] for move in restored["moves"]] == [move["uci"] for move in game["moves"]]
    assert restored["fen"] == game["fen"]


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


@pytest.mark.parametrize("fen", [chess.STARTING_FEN, "6k1/8/8/8/8/8/4r3/4K3 w - - 0 1"])
def test_two_hint_levels_reveal_source_then_destination(signed, fen):
    board = chess.Board(fen)
    source = None
    hinted_move = None
    for level in range(1, 3):
        response = signed.post("/api/hint", json={"fen": fen, "level": level})
        assert response.status_code == 200, response.text
        assert not response.json().get("candidates")
        if level == 1:
            square = response.json().get("highlight_square")
            assert square in chess.SQUARE_NAMES
            source = square
            assert board.piece_at(chess.parse_square(square)).color == board.turn
            assert response.json().get("highlight_move") is None
        else:
            move = response.json()["highlight_move"]
            assert move[:2] == source
            assert chess.Move.from_uci(move) in board.legal_moves
            if hinted_move is not None:
                assert move == hinted_move
            hinted_move = move
        if level <= 2:
            assert not response.json().get("insights") and not response.json().get("variations")
    for level in (3, 4):
        assert signed.post("/api/hint", json={"fen": fen, "level": level}).status_code == 422


def test_imported_game_analysis_is_resumable_grades_both_sides_and_preserves_moves(signed, monkeypatch):
    from src.backend.engine import engine_service
    calls = []
    def grade(board, move, **kwargs):
        calls.append((board.fen(), move.uci()))
        return {"fen": board.fen(), "move": move.uci(), "classification": "Good", "confidence": "engine_estimate",
                "text": "Good. Your move develops your position.", "facts": {}}
    monkeypatch.setattr(engine_service, "grade", grade)
    game = start(signed, mode="analysis", pgn="1. e4 e5 2. Nf3 Nc6 *")
    url = f"/api/games/{game['id']}"
    first = signed.post(url + "/analyze", json={"revision": 0, "limit": 2})
    assert first.status_code == 200, first.text
    assert first.json() == {"game_id": game["id"], "revision": 1, "analyzed": 2, "total": 4, "next_ply": 2, "complete": False}
    assert signed.post(url + "/analyze", json={"revision": 0, "start_ply": 2}).status_code == 409
    second = signed.post(url + "/analyze", json={"revision": 1, "start_ply": 2})
    assert second.status_code == 200 and second.json()["complete"]
    assert len(calls) == 4
    analyzed = signed.get(url).json()
    assert analyzed["fen"] == game["fen"]
    assert [record["uci"] for record in analyzed["moves"]] == [record["uci"] for record in game["moves"]]
    black = analyzed["moves"][1]["feedback"]
    assert black["actor"] == "opponent" and black["actor_color"] == "black"
    assert "Black's" in black["text"] and "Your" not in black["text"]


def test_opponent_feedback_does_not_reveal_the_learners_best_reply(signed, monkeypatch):
    from src.backend.engine import engine_service
    monkeypatch.setattr(engine_service, "play", lambda board, difficulty: board.parse_san("e5"))
    def grade(board, move, **kwargs):
        return {"fen": board.fen(), "move": move.uci(), "classification": "Mistake", "confidence": "engine_estimate",
                "text": "The engine's top choice was c5. Its strongest reply to your move is Nf3; your move gives up evaluation.",
                "best": {"san": "c5"}, "played": {"pv": ["e5", "Nf3"], "pv_uci": ["e7e5", "g1f3"]}}
    monkeypatch.setattr(engine_service, "grade", grade)
    game = start(signed, pgn="1. e4 *")
    response = signed.post(f"/api/games/{game['id']}/computer", json={"revision": 0})
    assert response.status_code == 200, response.text
    feedback = response.json()["moves"][-1]["feedback"]
    assert feedback["actor"] == "opponent" and "Black's" in feedback["text"]
    assert "Nf3" not in feedback["text"] and "c5" not in feedback["text"]
    assert "pv" not in feedback["played"]


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


def test_coach_preserves_game_repetition_history_without_contaminating_earlier_positions(signed, monkeypatch):
    from src.backend.coach import coach_service
    game = start(signed, mode="analysis", pgn="1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 *")
    captured = []
    original = coach_service.context
    def observe(board, *args, **kwargs):
        captured.append({"stack": [move.uci() for move in board.move_stack], "repetition": board.can_claim_threefold_repetition()})
        return original(board, *args, **kwargs)
    monkeypatch.setattr(coach_service, "context", observe)
    request = {"game_id": game["id"], "revision": 0, "question": "What should I do now?", "teaching_mode": "guided"}
    terminal = signed.post("/api/coach", json={**request, "fen": game["fen"]})
    assert terminal.status_code == 200, terminal.text
    assert captured[-1]["repetition"] and len(captured[-1]["stack"]) == 8
    assert "threefold repetition" in terminal.text and "finished position" in terminal.text
    assert "Which legal checks and captures" not in terminal.text
    earlier = signed.post("/api/coach", json={**request, "fen": game["moves"][2]["fen"]})
    assert earlier.status_code == 200, earlier.text
    assert not captured[-1]["repetition"] and captured[-1]["stack"] == ["g1f3", "g8f6", "f3g1"]
    assert "threefold repetition" not in earlier.text
    variation = signed.post("/api/coach", json={**request, "fen": game["moves"][2]["fen"], "moves": ["f6g8"], "explore": True})
    assert variation.status_code == 200, variation.text
    assert captured[-1]["stack"] == ["g1f3", "g8f6", "f3g1", "f6g8"] and not captured[-1]["repetition"]


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


def test_coach_reviews_assessed_moves_up_to_selected_position(signed, monkeypatch):
    from src.backend.engine import engine_service
    monkeypatch.setattr(engine_service, "play", lambda board, difficulty: chess.Move.from_uci("e7e5"))
    game = start(signed)
    url = f"/api/games/{game['id']}"
    first = signed.post(url + "/moves", json={"move": "e4", "revision": 0}).json()
    signed.post(url + "/computer", json={"revision": 1})
    game = signed.post(url + "/moves", json={"move": "Nf3", "revision": 2}).json()
    for fen, count, last_move in [(game["fen"], 2, "Nf3"), (first["fen"], 1, "e4")]:
        response = signed.post("/api/coach", json={"fen": fen, "game_id": game["id"], "revision": 3,
                                                     "question": "How has my moves been so far?"})
        assert response.status_code == 200
        assert f"Reviewed {count} of your moves" in response.text
        assert f"earlier decision {last_move}" in response.text
        assert '"fallback_reason": "not_configured"' in response.text
        if count == 1:
            assert "Nf3" not in response.text


def test_coach_review_without_assessments_is_explicit(signed):
    game = start(signed)
    response = signed.post("/api/coach", json={"fen": game["fen"], "game_id": game["id"], "revision": 0,
                                                 "question": "How have my moves been so far?"})
    assert "no assessed moves" in response.text


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


def test_computer_replies_default_on_and_saved_pause_survives_profile_switch(client):
    registered = client.post("/api/profiles", json={"name": "automatic-replies"})
    assert registered.status_code == 201
    profile_id = registered.json()["id"]
    client.headers["X-Profile-ID"] = profile_id
    assert registered.json()["preferences"]["auto_computer"] is True
    assert client.get("/api/settings").json()["auto_computer"] is True

    paused = client.patch("/api/settings", json={"auto_computer": False})
    assert paused.status_code == 200 and paused.json()["auto_computer"] is False
    updated = client.patch("/api/settings", json={"feedback": "detailed"})
    assert updated.status_code == 200 and updated.json()["auto_computer"] is False

    other = client.post("/api/profiles", json={"name": "other"}).json()
    client.headers["X-Profile-ID"] = other["id"]
    assert client.get("/api/settings").json()["auto_computer"] is True
    client.headers["X-Profile-ID"] = profile_id
    profiles = client.get("/api/profiles").json()
    selected = next(profile for profile in profiles if profile["id"] == profile_id)
    assert selected["preferences"]["auto_computer"] is False
    assert client.get("/api/settings").json()["auto_computer"] is False
