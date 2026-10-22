"""Adaptive projections derived from immutable exercise attempts and saved games."""
from collections import defaultdict
from bisect import bisect_left
import json
from types import SimpleNamespace

import chess
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from .exercises import CATEGORIES, objective_met, parse_move
from .models import Game, GameEvent, HintUsage, User, now
from .learning_models import LearningEvent
from .learning_evidence import SKILL_LABELS, grade_is_usable, observed_skills, position_key, topic_for, utc_iso
from .training_models import Exercise, ExerciseAttempt, HintEvent, LearningProgress


def progress_data(db: Session, user: User) -> dict:
    attempts = db.scalars(select(ExerciseAttempt).where(ExerciseAttempt.user_id == user.id)
                         .order_by(ExerciseAttempt.created_at)).all()
    topics: dict[str, dict] = {t: {"topic": t, "attempts": 0, "correct": 0, "independent": 0} for t in CATEGORIES}
    timeline: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "correct": 0})
    recent: dict[str, list] = defaultdict(list)
    failures: dict[str, int] = defaultdict(int)
    baseline = {"beginner": 1, "intermediate": 2, "advanced": 3}.get(user.preferences.get("complexity", "beginner"), 1)
    calculations = db.scalars(select(LearningEvent).where(LearningEvent.user_id == user.id,
        LearningEvent.kind == "calculation_attempt").order_by(LearningEvent.created_at)).all()
    for attempt in attempts:
        if attempt.correct and not attempt.complete:
            continue
        entry = topics.get(attempt.topic)
        if entry is None:
            continue
        entry["attempts"] += 1
        entry["correct"] += int(attempt.correct)
        independent = attempt.correct and not attempt.hint_level and attempt.evidence.get("independent", True)
        entry["independent"] += int(independent)
        recent[attempt.topic].append((attempt, independent))
        if attempt.correct:
            failures.pop(attempt.exercise_id, None)
        else:
            failures[attempt.exercise_id] += 1
        day = attempt.created_at.date().isoformat()
        timeline[day]["attempts"] += 1
        timeline[day]["correct"] += int(attempt.correct)
    for event in calculations:
        payload, entry = event.payload, topics.get(event.topic)
        if entry is None or payload.get("correct") is None: continue
        correct, independent = payload["correct"], payload.get("independent", False)
        entry["attempts"] += 1
        entry["correct"] += int(correct)
        entry["independent"] += int(independent)
        recent[event.topic].append((SimpleNamespace(correct=correct, evidence=payload, created_at=event.created_at), independent))
        day = event.created_at.date().isoformat()
        timeline[day]["attempts"] += 1
        timeline[day]["correct"] += int(correct)
    for topic in topics.values():
        topic["accuracy"] = round(topic["correct"] / topic["attempts"], 3) if topic["attempts"] else 0
        samples = sorted(recent[topic["topic"]], key=lambda pair: pair[0].created_at)[-10:]
        weights = [.85 ** (len(samples) - index - 1) for index in range(len(samples))]
        # Assisted success is useful progress, but is weaker mastery evidence than an independent solve.
        topic["mastery"] = round(sum(weight * (1 if independent else .35 if attempt.correct else 0)
                                     for weight, (attempt, independent) in zip(weights, samples)) / sum(weights), 3) if samples else 0
        topic["recent_accuracy"] = round(sum(a.correct for a, _ in samples) / len(samples), 3) if samples else 0
        topic["independent_accuracy"] = round(topic["independent"] / topic["attempts"], 3) if topic["attempts"] else 0
        topic["trend"] = ("improving" if topic["recent_accuracy"] > topic["accuracy"] + .1 else
                          "declining" if topic["recent_accuracy"] < topic["accuracy"] - .1 else "steady")
        practiced = [a.evidence.get("difficulty", baseline) for a, _ in samples]
        target = round(sum(practiced) / len(practiced)) if practiced else baseline
        adjustment = 1 if len(samples) >= 3 and topic["mastery"] >= .8 else -1 if len(samples) >= 2 and topic["mastery"] < .45 else 0
        topic["suggested_difficulty"] = max(1, min(5, target + adjustment))
        topic["strength"] = "developing" if topic["attempts"] < 3 else "strength" if topic["mastery"] >= .8 else "practice"
    total, correct = sum(t["attempts"] for t in topics.values()), sum(t["correct"] for t in topics.values())
    games = db.scalars(select(Game).where(Game.user_id == user.id).order_by(Game.created_at.desc()).limit(120)).all()
    games.reverse()
    mistakes: dict[str, int] = defaultdict(int)
    games_played = db.scalar(select(func.count(Game.id)).where(Game.user_id == user.id, cast(Game.moves, String) != "[]")) or 0
    game_performance = []
    for game in games:
        board = chess.Board(game.initial_fen)
        assessed = sound = errors = 0
        for move in game.moves:
            feedback = move.get("feedback") or {}
            # Only computer/training games provide a comparable, game-bound sample.
            if game.mode in ("computer", "training") and game.learning_source == "game" and board.turn == (game.player_color == "white") and move.get("assistance", {}).get("category") == "independent":
                classification = str(feedback.get("classification", "")).lower()
                if classification in {"best", "excellent", "good", "inaccuracy", "mistake", "blunder", "forced"}:
                    assessed += 1
                    sound += int(classification in {"best", "excellent", "good", "forced"})
                    errors += int(classification in {"inaccuracy", "mistake", "blunder"})
            if board.turn == (game.player_color == "white") and feedback.get("classification") in ("Mistake", "Blunder"):
                topic = "endgame" if len(board.piece_map()) <= 10 else "opening" if board.fullmove_number <= 10 else "middlegame"
                best_uci = (feedback.get("best") or {}).get("uci")
                if best_uci:
                    try:
                        best_move = parse_move(board, best_uci)
                        for motif_topic, kind in (("forks", "fork"), ("pins", "pin"), ("skewers", "skewer")):
                            if objective_met(board, best_move, {"kind": kind}):
                                topic = motif_topic
                                break
                    except ValueError:
                        pass
                mistakes[topic] += 1
            board.push_uci(move["uci"])
        if assessed:
            game_performance.append({
                "game_id": game.id,
                "date": game.created_at.date().isoformat(),
                "assessed_moves": assessed,
                "sound_moves": sound,
                "errors": errors,
                "sound_rate": round(sound / assessed, 3),
            })
    due = db.scalars(select(LearningProgress).where(LearningProgress.user_id == user.id, LearningProgress.due_at <= now())).all()
    exercise_ids = [exercise_id for exercise_id, count in failures.items() if count >= 2]
    repeated = [{"exercise_id": exercise.id, "topic": exercise.category, "title": exercise.data["title"],
                 "failures": failures[exercise.id]}
                for exercise in db.scalars(select(Exercise).where(Exercise.id.in_(exercise_ids)))] if exercise_ids else []
    repeated.sort(key=lambda entry: (-entry["failures"], entry["exercise_id"]))
    for topic in topics.values():
        topic["due"] = sum(review.topic == topic["topic"] for review in due)
        topic["repeated_mistakes"] = sum(entry["topic"] == topic["topic"] for entry in repeated)
    ranked = sorted(topics.values(), key=lambda x: (x["mastery"] if x["attempts"] else .65)
                    - min(.5, mistakes[x["topic"]] * .1) - min(.3, x["repeated_mistakes"] * .15))
    recommendations = [{"topic": t["topic"], "reason": (
        "Repeated mistakes suggest revisiting this idea with a simpler exercise." if t["repeated_mistakes"] else
        "Review this concept after mistakes in your games." if mistakes[t["topic"]] else
        "Strengthen a topic that has been difficult." if t["attempts"] else "Build a foundation with a short lesson."),
        "label": t["topic"].title(), "kind": t["topic"], "suggested_difficulty": t["suggested_difficulty"]} for t in ranked[:3]]
    hint_count = len(db.scalars(select(HintEvent.id).where(HintEvent.user_id == user.id)).all())
    hint_count += len(db.scalars(select(HintUsage.id).where(HintUsage.user_id == user.id)).all())
    learning = learning_observations(db, user, attempts, calculations, games)
    if user.preferences.get("language") == "da":
        labels = {"forks": "Gafler", "pins": "Bindinger", "skewers": "Spidninger", "opening": "Åbning", "middlegame": "Midtspil", "endgame": "Slutspil"}
        for item in recommendations:
            topic = topics[item["topic"]]
            item.update(label=labels[item["topic"]], reason=("Gentagne fejl peger på, at du bør øve idéen med en enklere øvelse." if topic["repeated_mistakes"] else
                        "Øv et emne med fejl i dine partier." if mistakes[item["topic"]] else "Styrk dette emne med en kort øvelse."))
    return {"games_played": games_played, "evidence_window_games": 120, "attempts": total, "correct": correct,
            "accuracy": round(correct / total, 3) if total else 0, "hints_used": hint_count,
            "topics": list(topics.values()), "recommendations": recommendations, "due_reviews": len(due),
            "game_mistakes": dict(mistakes), "repeated_mistakes": repeated,
            "timeline": [{"date": date, **v} for date, v in sorted(timeline.items())],
            "game_performance": sorted(game_performance, key=lambda item: item["date"])[-20:], **learning}


def learning_observations(db: Session, user: User, attempts: list, calculations: list, games: list) -> dict:
    """Combine auditable practice and subsequent live decisions without asserting causation."""
    exercises = {item.id: item for item in db.scalars(select(Exercise).where(
        Exercise.id.in_({attempt.exercise_id for attempt in attempts})))}
    skills: dict[str, dict] = {}
    trained = []
    da = user.preferences.get("language") == "da"
    def observe(names: list[str], correct: bool, independent: bool, source: str):
        for name in names:
            if name not in SKILL_LABELS: continue
            entry = skills.setdefault(name, {"skill": name, "label": SKILL_LABELS[name][int(da)],
                "observations": 0, "correct": 0, "mistakes": 0, "independent": 0, "sources": {}})
            entry["observations"] += 1
            entry["correct"] += int(correct)
            entry["mistakes"] += int(not correct)
            entry["independent"] += int(independent)
            entry["sources"][source] = entry["sources"].get(source, 0) + 1
    for attempt in attempts:
        item = exercises.get(attempt.exercise_id)
        if item is None or attempt.correct and not attempt.complete: continue
        data = item.data
        if not data.get("evidence", {}).get("objective_verified"): continue
        board = chess.Board(data["fen"])
        expected = parse_move(board, data["solution"][0])
        names = observed_skills(board, expected, criterion=data["criterion"])
        if len(data["solution"]) > 1: names = sorted(set(names) | {"calculation_response"})
        observe(names, attempt.correct, attempt.correct and not attempt.hint_level and attempt.evidence.get("independent", True), "exercise")
        if attempt.correct and attempt.complete:
            trained.append({"fen": position_key(data["fen"]), "topic": item.category,
                "pattern": data["criterion"], "created_at": attempt.created_at, "source": "exercise", "id": item.id})
    assessed, accurate, response_assessed, response_accurate, judged, agreements = 0, 0, 0, 0, 0, 0
    for event in calculations:
        payload = event.payload
        assessed += payload.get("assessed_plies", 0)
        accurate += payload.get("accurate_plies", 0)
        for step in payload.get("steps", []):
            if step["classification"] == "Uncertain": continue
            correct = step["classification"] not in ("Inaccuracy", "Mistake", "Blunder")
            observe(step.get("skills", []), correct, correct and not payload.get("hint_level") and not payload.get("retry_count"), "calculation")
            if step.get("role") == "opponent_response":
                response_assessed += 1
                response_accurate += int(correct)
        if payload.get("assessment_agrees") is not None:
            judged += 1
            agreements += int(payload["assessment_agrees"])
        if payload.get("correct") is True:
            trained.append({"fen": position_key(event.fen), "topic": event.topic,
                "pattern": {"kind": {"forks": "fork", "pins": "pin", "skewers": "skewer"}.get(event.topic, "engine")},
                "created_at": event.created_at, "source": "calculation", "id": event.id})
    by_game = {game.id: game for game in games if game.mode != "analysis" and game.learning_source == "game"}
    by_position, by_pattern = defaultdict(list), {}
    for practice in sorted(trained, key=lambda item: item["created_at"]):
        by_position[practice["fen"]].append(practice)
        criterion = practice["pattern"]
        if criterion.get("kind") not in ("engine", "capture", "king_activity"):
            signature = json.dumps(criterion, sort_keys=True)
            by_pattern.setdefault(signature, {"criterion": criterion, "history": []})["history"].append(practice)
    def previous_practice(history: list, played_at):
        index = bisect_left(history, played_at, key=lambda item: item["created_at"])
        return history[index - 1] if index else None
    events = db.scalars(select(GameEvent).where(GameEvent.game_id.in_(by_game),
        GameEvent.kind == "move").order_by(GameEvent.created_at)).all() if by_game else []
    transfers = []
    for event in events:
        record, game = event.payload, by_game[event.game_id]
        if record.get("source") != "player" or record.get("color") != game.player_color: continue
        feedback = record.get("feedback") or {}
        if not grade_is_usable(feedback) or not record.get("before_fen"): continue
        try:
            board = chess.Board(record["before_fen"])
            best = parse_move(board, feedback["best"]["uci"])
            played = parse_move(board, record["uci"])
            if feedback.get("fen") != board.fen() or feedback["played"].get("uci") != played.uci(): continue
        except (ValueError, KeyError): continue
        names = sorted(set(observed_skills(board, played, feedback)) | set(observed_skills(board, best, feedback)))
        correct = feedback["classification"] in ("Best", "Excellent", "Good", "Forced")
        independent = record.get("assistance", {}).get("category") == "independent"
        observe(names, correct, correct and independent, "game")
        eligible = []
        exact = previous_practice(by_position.get(position_key(board.fen()), []), event.created_at)
        if exact: eligible.append((True, exact))
        for pattern in by_pattern.values():
            practice = previous_practice(pattern["history"], event.created_at)
            if practice and objective_met(board, best, pattern["criterion"]): eligible.append((False, practice))
        if eligible:
            exact, practice = max(eligible, key=lambda pair: (pair[0], pair[1]["created_at"]))
            transfers.append({"game_id": game.id, "revision": event.revision, "topic": practice["topic"],
                "move": played.uci(), "san": record.get("san", board.san(played)), "fen": board.fen(),
                "match": "same_position" if exact else "same_verified_pattern", "practice_source": practice["source"],
                "practice_id": practice["id"], "trained_at": utc_iso(practice["created_at"]),
                "played_at": utc_iso(event.created_at), "classification": feedback["classification"], "sound": correct,
                "assistance": record.get("assistance", {}).get("category", "unknown"),
                "independent": independent, "evidence": {"best_move": best.uci(), "loss_cp": feedback.get("loss_cp"), "confidence": feedback["confidence"]}})
    for entry in skills.values():
        entry["accuracy"] = round(entry["correct"] / entry["observations"], 3)
        entry["priority"] = "practice" if entry["mistakes"] >= 2 else "strength" if entry["observations"] >= 12 and entry["independent"] >= 12 and not entry["mistakes"] else "observe"
    return {"calculation": {"attempts": len(calculations), "assessed_plies": assessed, "accurate_plies": accurate,
        "accuracy": round(accurate / assessed, 3) if assessed else None,
        "response_accuracy": round(response_accurate / response_assessed, 3) if response_assessed else None,
        "final_assessment_accuracy": round(agreements / judged, 3) if judged else None,
        "independent_solves": sum(event.payload.get("independent", False) for event in calculations),
        "hints_used": sum(event.payload.get("hint_level", 0) > 0 for event in calculations)},
        "observed_skills": sorted(skills.values(), key=lambda entry: (-entry["mistakes"], entry["skill"])),
        "transfer": {"decisions": len(transfers), "sound_decisions": sum(item["sound"] for item in transfers),
            "independent_decisions": sum(item["independent"] for item in transfers),
            "independent_sound_decisions": sum(item["independent"] and item["sound"] for item in transfers),
            "samples": transfers[-20:], "qualification": ("Observerede matchende beslutninger efter træning; det dokumenterer ikke, at træningen var årsag til resultatet." if da else "Observed matching decisions after practice; this does not establish that practice caused the result.")}}


