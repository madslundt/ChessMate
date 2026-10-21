"""Position-scoped conversational references, separate from chess evidence."""
from copy import deepcopy
import re


def follow_up_kind(question: str) -> str | None:
    text = re.sub(r"[^\w\s]", "", question.lower()).strip()
    text = " ".join(text.split())
    if text in {"why", "why is that", "why that move", "why that one", "why exactly", "why do you say that",
                "explain", "explain more", "tell me more", "how so", "what do you mean", "can you explain",
                "hvorfor", "hvorfor det", "hvorfor det træk", "forklar", "forklar mere", "uddyb", "hvordan det"}:
        return "why"
    if text in {"show me", "show it", "show that", "show me on the board", "vis mig", "vis det", "vis på brættet"}:
        return "show"
    return None


def resolve_question(question: str, history: list[dict], topic: dict | None, fen: str) -> tuple[str, str | None, dict | None]:
    kind = follow_up_kind(question)
    if topic and topic.get("fen") == fen and isinstance(topic.get("question"), str):
        if kind or not question.strip() or question.strip().lower() == topic["question"].strip().lower():
            return topic["question"], kind, deepcopy(topic)
    if kind:
        for message in reversed(history):
            if (message.get("role") == "user" and message.get("fen") in (None, fen)
                    and message.get("content", "").strip() and not follow_up_kind(message["content"])):
                return message["content"], kind, None
    return question, kind, None


def topic_snapshot(context: dict, focus: dict | None) -> dict:
    return deepcopy({"fen": context["fen"], "question": context["question"],
        "piece_choice": context.get("piece_choice"), "requested_candidates": context.get("requested_candidates", []),
        "unavailable_piece_choices": context.get("unavailable_piece_choices", []), "focus_candidate": focus})
