"""Evidence-grounded daily diary and on-demand reports; no scheduled period summaries.

Game/assistance records remain source evidence. These projections can be rebuilt,
without changing those records or relying on the availability of a language model.
"""
import calendar
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .database import get_db
from .diary_models import DailyDiary, ProgressReport
from .models import Game, User, now, uid
from .schemas import Input

router = APIRouter(prefix="/diary", tags=["Diary"])
CONCEPT_LABELS = {
    "forks": ("Forks", "Gafler"), "pins": ("Pins", "Bindinger"), "skewers": ("Skewers", "Spidninger"),
    "opening": ("Development", "Udvikling"), "middlegame": ("Middlegame decisions", "Midtspilsbeslutninger"),
    "endgame": ("Endgames", "Slutspil"), "endgames": ("Endgame decisions", "Slutspilsbeslutninger"),
    "forcing_moves": ("Checks, captures and threats", "Skakker, slag og trusler"),
    "defense": ("Opponent threats", "Modstanderens trusler"), "safety": ("Piece and king safety", "Brik- og kongesikkerhed"),
    "calculation_response": ("Predicting replies", "Forudsig modstanderens svar"),
    "exchanges": ("Exchanges", "Afbytninger"), "plans": ("Position-specific plans", "Stillingsbestemte planer"),
}


def concept_label(topic, da=False):
    return CONCEPT_LABELS.get(topic, (topic.replace("_", " ").title(), topic.replace("_", " ").title()))[int(da)]


def user_zone(user):
    return ZoneInfo((user.preferences or {}).get("timezone", "UTC"))


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def date_bounds(day, zone, end=None):
    if day.year < 12 or day.year >= 9999 or end and (end.year < 12 or end.year >= 9999):
        raise HTTPException(422, "Date is outside the supported calendar")
    return (datetime.combine(day, time.min, zone).astimezone(timezone.utc),
            datetime.combine((end or day) + timedelta(days=1), time.min, zone).astimezone(timezone.utc))


def analyses_for(db, ids):
    from .learning_models import GameLearningAnalysis
    return {row.game_id: row for row in db.scalars(select(GameLearningAnalysis).where(GameLearningAnalysis.game_id.in_(ids)))} if ids else {}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def empty_statistics():
    return {key: 0 for key in ("games", "wins", "draws", "losses", "independent", "assisted", "unknown", "independent_sound", "assisted_sound", "analyzed_games", "forced")}


def daily_evidence(db, user, day):
    start, end = date_bounds(day, user_zone(user))
    games = db.scalars(select(Game).where(Game.user_id == user.id, Game.completed_at >= start,
        Game.completed_at < end).order_by(Game.completed_at, Game.id)).all()
    analyses = analyses_for(db, [game.id for game in games])
    statistics = empty_statistics()
    source_statistics = {}
    observations, summaries = [], []
    topics = Counter()
    for game in games:
        from .games import completed_result
        result = completed_result(game)
        source = getattr(game, "learning_source", "game")
        source_stats = source_statistics.setdefault(source, empty_statistics())
        statistics["games"] += 1
        source_stats["games"] += 1
        if result != "*":
            key = "draws" if result == "1/2-1/2" else "wins" if (result == "1-0") == (game.player_color == "white") else "losses"
            statistics[key] += 1
            source_stats[key] += 1
        analysis = analyses.get(game.id)
        status = analysis.status if analysis else "pending"
        summaries.append({"id": game.id, "result": result, "difficulty": game.difficulty,
            "analysis_status": status, "source": getattr(game, "learning_source", "unknown"),
            "completed_at": aware(game.completed_at).isoformat()})
        if not analysis or status != "completed": continue
        statistics["analyzed_games"] += 1
        source_stats["analyzed_games"] += 1
        for original in (analysis.evidence or {}).get("observations", []):
            # Count each player decision once. Imported and historical unknowns
            # never become independent evidence merely by being reanalyzed.
            item = dict(original)
            item.update(game_id=game.id)
            category = item.get("assistance", "unknown")
            if isinstance(category, dict): category = category.get("category", "unknown")
            group = "independent" if category == "independent" else "unknown" if category == "unknown" else "assisted"
            if item.get("forced"):
                statistics["forced"] += 1
                source_stats["forced"] += 1
            else:
                statistics[group] += 1
                source_stats[group] += 1
                if group != "unknown":
                    statistics[group + "_sound"] += int(bool(item.get("sound")))
                    source_stats[group + "_sound"] += int(bool(item.get("sound")))
            item["assistance"] = category
            item["concepts"] = item.get("skills", [])
            item["text"] = observation_text(item, (user.preferences or {}).get("coach_language") == "da")
            observations.append(item)
            if item.get("classification") in ("Mistake", "Blunder"):
                topics[item.get("topic", "mixed")] += 1
    statuses = [item["analysis_status"] for item in summaries]
    status = "completed" if statuses and all(s == "completed" for s in statuses) else "partial" if "completed" in statuses else "failed" if statuses and all(s == "failed" for s in statuses) else "pending"
    da = (user.preferences or {}).get("coach_language") == "da"
    recommendations = [{"topic": topic, "label": concept_label(topic, da)}
        for topic, _ in topics.most_common(2)]
    from .learning_models import PlayerLearningState
    profile = db.get(PlayerLearningState, user.id)
    existing = db.scalar(select(DailyDiary).where(DailyDiary.user_id == user.id, DailyDiary.date == day))
    snapshot = existing.evidence.get("profile_snapshot") if existing and existing.timezone == str(user_zone(user)) else None
    if snapshot:
        try:
            if aware(datetime.fromisoformat(snapshot["as_of"])) >= end: snapshot = None
        except (KeyError, ValueError): snapshot = None
    # A historical diary must never borrow a future learning conclusion.
    if profile and aware(profile.updated_at) < end:
        snapshot = {"as_of": aware(profile.updated_at).isoformat(),
            "adaptive_difficulty": profile.data.get("adaptive_difficulty", 1),
            "sample_games": profile.data.get("sample_games", 0),
            "concepts": profile.data.get("concepts", []),
            "recommendations": profile.data.get("recommendations", [])}
    return {"statistics": statistics, "games": summaries, "observations": observations,
        "profile_snapshot": snapshot, "source_statistics": source_statistics,
        "recommendations": recommendations, "status": status,
        "analysis_versions": {key: {"version": getattr(value, "version", None), "evidence": digest(value.evidence or {}), "status": value.status} for key, value in analyses.items()}}


def observation_text(item, da):
    feedback = item.get("engine_analysis") or {}
    # Existing deterministic feedback is already tied to the analyzed FEN.
    text = feedback.get("consequence") or feedback.get("text")
    if text: return text
    if item.get("classification") in ("Mistake", "Blunder"):
        return "Undersøg modstanderens skakker, slag og trusler i denne stilling." if da else "Review the opponent's checks, captures and threats in this position."
    return "Et observeret valg i denne stilling; ét valg dokumenterer ikke beherskelse." if da else "An observed decision in this position; one decision does not establish mastery."


def narrative(evidence, da=False):
    s = evidence["statistics"]
    if da:
        paragraphs = [f"Du afsluttede {s['games']} {'parti' if s['games'] == 1 else 'partier'}: {s['wins']} vundne, {s['draws']} remis og {s['losses']} tabte."]
        paragraphs.append(f"{s['independent']} vurderede beslutninger var selvstændige, {s['assisted']} fik hjælp, og {s['unknown']} har ukendt hjælpestatus.")
        if s["independent"]: paragraphs.append(f"{s['independent_sound']} af de selvstændige beslutninger var rimelige ifølge den gemte motorvurdering.")
        if evidence["status"] != "completed": paragraphs.append("Analysen er ufuldstændig. Konklusioner bygger kun på færdiganalyserede partier.")
        if evidence["recommendations"]: paragraphs.append("Næste fokus: " + ", ".join(item["label"] for item in evidence["recommendations"]) + ". Åbn de markerede stillinger, og undersøg modstanderens svar før dit næste træk.")
        paragraphs.append("Dagens observationer alene dokumenterer ikke en varig styrke eller svaghed. Sammenlign selvstændige valg over flere partier.")
    else:
        plural = lambda count, singular, many: singular if count == 1 else many
        paragraphs = [f"You completed {s['games']} {plural(s['games'], 'game', 'games')}: {s['wins']} {plural(s['wins'], 'win', 'wins')}, {s['draws']} {plural(s['draws'], 'draw', 'draws')} and {s['losses']} {plural(s['losses'], 'loss', 'losses')}."]
        paragraphs.append(f"{s['independent']} assessed decisions were independent, {s['assisted']} received assistance and {s['unknown']} have unknown assistance history.")
        if s["independent"]: paragraphs.append(f"{s['independent_sound']} of your independent decisions were reasonable according to the stored engine assessment.")
        if evidence["status"] != "completed": paragraphs.append("Analysis is incomplete. Observations use only games whose analysis has finished.")
        if evidence["recommendations"]: paragraphs.append("Next focus: " + ", ".join(item["label"] for item in evidence["recommendations"]) + ". Open the highlighted positions and examine the opponent's replies before choosing your next move.")
        paragraphs.append("Today's observations alone do not establish a lasting strength or weakness. Compare independent decisions across several games.")
    snapshot = evidence.get("profile_snapshot") or {}
    meaningful = [item for item in snapshot.get("concepts", []) if item.get("status") in
        ("recurring_weakness", "improving", "declining", "consistently_demonstrated_strength")]
    words = {"recurring_weakness": ("recurring difficulty", "tilbagevendende udfordring"),
        "improving": ("improving", "i fremgang"), "declining": ("needs renewed attention", "kræver fornyet opmærksomhed"),
        "consistently_demonstrated_strength": ("consistently demonstrated strength", "stabilt demonstreret styrke")}
    for item in meaningful[:2]:
        topic = concept_label(item["topic"], da)
        paragraphs.append((f"Den gemte læringsprofil beskriver {topic} som {words[item['status']][1]}, baseret på {item.get('independent', 0)} selvstændige observationer fra {item.get('games', 0)} partier." if da else
            f"The saved learning profile describes {topic} as {words[item['status']][0]}, supported by {item.get('independent', 0)} independent observations across {item.get('games', 0)} games."))
    sound = [o for o in evidence.get("observations", []) if o.get("sound") and o.get("assistance") == "independent" and not o.get("forced")]
    if sound:
        examples = ", ".join(f"{o.get('san', o.get('played_move', ''))} ({concept_label(o.get('topic', ''), da)})" for o in sound[:2])
        paragraphs.insert(2, ("Selvstændige valg at genbesøge: " if da else "Independent decisions to revisit: ") + examples + ".")
    return "\n\n".join(paragraphs)


def rebuild_day(db, user, day, force=False):
    # FOR NO KEY UPDATE serializes same-user projections while remaining
    # compatible with the FK key-share locks acquired by concurrent game inserts.
    db.scalar(select(User).where(User.id == user.id).with_for_update(key_share=True))
    evidence = daily_evidence(db, user, day)
    if not evidence["games"]:
        old = db.scalar(select(DailyDiary).where(DailyDiary.user_id == user.id, DailyDiary.date == day))
        if old: db.delete(old)
        return None
    zone = str(user_zone(user))
    fingerprint = digest({"evidence": evidence, "timezone": zone, "language": (user.preferences or {}).get("coach_language", "en"),
        "enabled": (user.preferences or {}).get("automatic_diary", True)})
    query = select(DailyDiary).where(DailyDiary.user_id == user.id, DailyDiary.date == day)
    row = db.scalar(query.with_for_update())
    if row and row.fingerprint == fingerprint and not (force and not row.summary): return row
    values = {"id": uid(), "user_id": user.id, "date": day, "timezone": zone, "version": 1,
        "fingerprint": fingerprint, "status": evidence["status"], "summary": "", "evidence": evidence, "updated_at": now()}
    if row is None:
        # Unique key and dialect upsert protect simultaneous game completions.
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        db.execute(insert(DailyDiary).values(**values).on_conflict_do_nothing(index_elements=["user_id", "date"]))
        row = db.scalar(query.with_for_update())
    else:
        row.version += 1
    row.timezone, row.fingerprint, row.status = zone, fingerprint, evidence["status"]
    row.evidence = evidence
    row.summary = narrative(evidence, (user.preferences or {}).get("coach_language") == "da") if force or (user.preferences or {}).get("automatic_diary", True) else ""
    row.updated_at = now()
    db.flush()
    return row


def sync_game_diary(db, game):
    if not game.completed_at: return
    user = db.get(User, game.user_id)
    if user:
        rebuild_day(db, user, aware(game.completed_at).astimezone(user_zone(user)).date())


def day_view(row):
    return {"date": row.date.isoformat(), "timezone": row.timezone, "version": row.version,
        "status": row.status, "summary": row.summary, **row.evidence, "updated_at": aware(row.updated_at).isoformat()}


@router.get("/calendar")
def calendar_view(month: str = Query(pattern=r"^\d{4}-\d{2}$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    try: first = date.fromisoformat(month + "-01")
    except ValueError: raise HTTPException(422, "Invalid calendar month") from None
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    start, end = date_bounds(first, user_zone(user), last)
    rows = db.execute(select(Game.id, Game.completed_at).where(Game.user_id == user.id,
        Game.completed_at >= start, Game.completed_at < end)).all()
    counts = Counter(aware(completed).astimezone(user_zone(user)).date() for _, completed in rows)
    diaries = {row.date: row for row in db.scalars(select(DailyDiary).where(DailyDiary.user_id == user.id,
        DailyDiary.date >= first, DailyDiary.date <= last))}
    return {"month": month, "timezone": str(user_zone(user)), "days": [{"date": day.isoformat(), "game_count": count,
        "status": diaries[day].status if day in diaries and diaries[day].timezone == str(user_zone(user)) else "pending",
        **{key: (diaries[day].evidence.get("statistics", {}).get(key, 0) if day in diaries and diaries[day].timezone == str(user_zone(user)) else 0) for key in ("wins", "draws", "losses")}}
        for day, count in sorted(counts.items())]}


@router.get("/days/{day}")
def get_day(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = rebuild_day(db, user, day)
    if not row: raise HTTPException(404, "No completed games on this date")
    db.commit()
    return day_view(row)


@router.post("/days/{day}/regenerate")
def regenerate_day(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = rebuild_day(db, user, day, force=True)
    if not row: raise HTTPException(404, "No completed games on this date")
    db.commit()
    return day_view(row)


class ReportRequest(Input):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date > self.end_date or (self.end_date - self.start_date).days > 3660:
            raise ValueError("Choose an ordered date range of at most ten years")
        if self.start_date.year < 12 or self.end_date.year >= 9999:
            raise ValueError("Date range is outside the supported calendar")
        return self


def aggregate_days(rows):
    statistics, observations, recommendations = empty_statistics(), {}, {}
    source_statistics = {}
    for row in rows:
        for key in statistics: statistics[key] += row.evidence.get("statistics", {}).get(key, 0)
        for source, values in row.evidence.get("source_statistics", {}).items():
            source_stats = source_statistics.setdefault(source, empty_statistics())
            for key in source_stats: source_stats[key] += values.get(key, 0)
        for item in row.evidence.get("observations", []): observations[(item["game_id"], item["ply"])] = item
        for item in row.evidence.get("recommendations", []): recommendations[item["topic"]] = item
    snapshot = next((row.evidence.get("profile_snapshot") for row in reversed(rows) if row.evidence.get("profile_snapshot")), None)
    concepts = (snapshot or {}).get("concepts", [])
    return {"statistics": statistics, "observations": list(observations.values()), "recommendations": list(recommendations.values())[:2],
        "profile_snapshot": snapshot, "source_statistics": source_statistics,
        "strengths": [item for item in concepts if item.get("status") == "consistently_demonstrated_strength"],
        "weaknesses": [item for item in concepts if item.get("status") in ("recurring_weakness", "emerging_weakness")],
        "improvements": [item for item in concepts if item.get("status") == "improving"],
        "status": "completed" if all(row.status == "completed" for row in rows) else "partial", "active_days": len(rows)}


def diaries_in(db, user, start, end):
    return db.scalars(select(DailyDiary).where(DailyDiary.user_id == user.id,
        DailyDiary.date >= start, DailyDiary.date <= end, DailyDiary.timezone == str(user_zone(user))).order_by(DailyDiary.date)).all()


def report_versions(db, user, start, end):
    return {row.date.isoformat(): {"version": row.version, "fingerprint": row.fingerprint} for row in diaries_in(db, user, start, end)}


def report_content(db, user, start, end):
    rows = diaries_in(db, user, start, end)
    content = aggregate_days(rows)
    content["diary_versions"] = report_versions(db, user, start, end)
    prior_end = start - timedelta(days=1)
    prior_start = start - timedelta(days=(end - start).days + 1)
    prior = aggregate_days(diaries_in(db, user, prior_start, prior_end))
    a, b = content["statistics"], prior["statistics"]
    current_games = content["source_statistics"].get("game", empty_statistics())
    prior_games = prior["source_statistics"].get("game", empty_statistics())
    comparable = min(current_games["independent"], prior_games["independent"]) >= 20 and min(current_games["analyzed_games"], prior_games["analyzed_games"]) >= 3
    content["comparison"] = {"start_date": prior_start.isoformat(), "end_date": prior_end.isoformat(),
        "sufficient_evidence": comparable, "statistics": prior_games, "source": "game",
        "independent_sound_rate_change": round(current_games["independent_sound"] / current_games["independent"] - prior_games["independent_sound"] / prior_games["independent"], 3) if comparable else None,
        "qualification": "Descriptive comparison only; opponent strength, position complexity and sample selection may differ."}
    # Detect missing diary days rather than silently representing these as complete.
    lower, upper = date_bounds(start, user_zone(user), end)
    count = db.scalar(select(func.count(Game.id)).where(Game.user_id == user.id, Game.completed_at >= lower, Game.completed_at < upper))
    content["missing_diary_games"] = max(0, count - a["games"])
    if content["missing_diary_games"]: content["status"] = "partial"
    content["summary"] = narrative(content, (user.preferences or {}).get("coach_language") == "da")
    content["source_fingerprint"] = source_fingerprint(db, user, start, end)
    return content


def source_fingerprint(db, user, start, end):
    from .learning_models import GameLearningAnalysis
    lower, upper = date_bounds(start, user_zone(user), end)
    rows = db.execute(select(Game.id, Game.revision, Game.completed_at, GameLearningAnalysis.status,
        GameLearningAnalysis.fingerprint, GameLearningAnalysis.version, GameLearningAnalysis.updated_at)
        .outerjoin(GameLearningAnalysis, GameLearningAnalysis.game_id == Game.id)
        .where(Game.user_id == user.id, Game.completed_at >= lower, Game.completed_at < upper).order_by(Game.id)).all()
    return digest({"timezone": str(user_zone(user)), "rows": [list(row) for row in rows]})


def report_view(db, user, row):
    return {"id": row.id, "start_date": row.start_date.isoformat(), "end_date": row.end_date.isoformat(),
        "status": row.status, **row.content, "created_at": aware(row.created_at).isoformat(),
        "outdated": (row.content.get("diary_versions") != report_versions(db, user, row.start_date, row.end_date)
            or row.content.get("source_fingerprint") != source_fingerprint(db, user, row.start_date, row.end_date))}


@router.post("/reports", status_code=201)
def create_report(data: ReportRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    content = report_content(db, user, data.start_date, data.end_date)
    row = ProgressReport(user_id=user.id, start_date=data.start_date, end_date=data.end_date, status=content["status"], content=content)
    db.add(row)
    db.commit()
    return report_view(db, user, row)


@router.get("/reports")
def list_reports(user: User = Depends(current_user), db: Session = Depends(get_db), offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    rows = db.scalars(select(ProgressReport).where(ProgressReport.user_id == user.id).order_by(ProgressReport.created_at.desc()).offset(offset).limit(limit)).all()
    return [report_view(db, user, row) for row in rows]


def owned_report(db, user, identifier):
    row = db.scalar(select(ProgressReport).where(ProgressReport.id == identifier, ProgressReport.user_id == user.id))
    if not row: raise HTTPException(404, "Report not found")
    return row


@router.get("/reports/{identifier}")
def get_report(identifier: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return report_view(db, user, owned_report(db, user, identifier))


@router.post("/reports/{identifier}/regenerate")
def regenerate_report(identifier: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = owned_report(db, user, identifier)
    row.content = report_content(db, user, row.start_date, row.end_date)
    row.status = row.content["status"]
    db.commit()
    return report_view(db, user, row)
