"""Recognize piece-choice questions and answer them from legal, root-restricted searches."""
import re

import chess

from .chess_tools import move_facts
from .engine import score_number

PIECES_DA = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning", "king": "konge"}
PIECE_TERMS = {chess.KNIGHT: ("knight", "horse", "springer", "hest"), chess.BISHOP: ("bishop", "løber"),
               chess.ROOK: ("rook", "tårn"), chess.QUEEN: ("queen", "dronning"),
               chess.PAWN: ("pawn", "bonde"), chess.KING: ("king", "konge")}


def piece_choice_request(question: str) -> dict | None:
    question = question.lower()
    development = "develop" in question or "udvikl" in question
    pieces = [piece for piece, terms in PIECE_TERMS.items()
              if any(re.search(r"\b" + term, question) for term in terms)]
    comparison = any(term in question for term in ("better than", "rather than", "compare", "bedre end", "sammenlign", "versus"))
    choice = bool(re.search(r"\b(or|eller|first|først|before|vs)\b", question))
    development_question = development and bool(re.search(r"\b(which|what|should|hvilken|hvilke|hvem|hvad|skal|bør|next|næste)\b", question))
    if development_question and not pieces:
        pieces = [chess.KNIGHT, chess.BISHOP]
    if pieces and (development_question or comparison or (len(pieces) >= 2 and choice)):
        return {"pieces": pieces[:2], "development": development}
    return None


def choice_moves(board: chess.Board, piece_type: int, development: bool) -> list[chess.Move]:
    return [move for move in board.legal_moves if board.piece_type_at(move.from_square) == piece_type
            and (not development or piece_type not in (chess.KNIGHT, chess.BISHOP)
                 or chess.square_rank(move.from_square) == (0 if board.turn else 7))]


def choice_recommendation(context: dict) -> dict | None:
    candidates = context.get("requested_candidates", [])
    if not candidates or not (context.get("piece_choice") or {}).get("analyzed"):
        return None
    if context.get("topic_focus"): return context["topic_focus"]
    best = max(candidates, key=score_number)
    global_best = next(iter(context["analysis"].get("candidates", [])), None)
    if global_best and score_number(global_best) - score_number(best) >= 150:
        return global_best
    return best


def piece_choice_statements(board: chess.Board, context: dict, language: str, reveal: bool) -> dict[str, str]:
    request = context.get("piece_choice")
    if not request or board.is_game_over(claim_draw=True):
        return {}
    da = language == "da"
    name = lambda piece: PIECES_DA[chess.piece_name(piece)] if da else chess.piece_name(piece)
    names = (" eller " if da else " or ").join(name(piece) for piece in request["pieces"])
    if context["learner_color"] != ("white" if board.turn else "black"):
        return {"piece_choice_answer": (f"Vent med valget mellem {names}, til modstanderen har svaret; det er ikke din tur." if da else
                                        f"Reassess {names} after the opponent replies; it is not your turn.")}
    available = [piece for piece in request["pieces"] if choice_moves(board, piece, request["development"])]
    missing = [piece for piece in request["pieces"] if piece not in available]
    candidates = context.get("requested_candidates", [])
    ranked = sorted(candidates, key=score_number, reverse=True)
    statements = {}
    if not reveal:
        statements["piece_choice_answer"] = (f"Sammenlign {names}: hvilken kan udvikles lovligt og lægge pres på centrum? Jeg holder de konkrete træk skjult som ønsket." if da else
            f"Compare {names}: which can develop legally and pressure the center? The concrete moves stay hidden as requested.")
        return statements
    if ranked and request.get("analyzed"):
        best = ranked[0]
        piece_name = name(board.piece_type_at(chess.Move.from_uci(best["uci"]).from_square))
        if len(ranked) > 1 and abs(score_number(best) - score_number(ranked[1])) <= 25:
            answer = (f"Begge muligheder vurderes næsten ens i den korte søgning. Du kan begynde med din {piece_name}." if da else
                      f"The short search rates both options similarly. You can start with your {piece_name}.")
        else:
            answer = (f"Jeg ville begynde med din {piece_name}. Den korte søgning foretrækker denne mulighed blandt de sammenlignede brikker." if da else
                      f"I would start with your {piece_name}. The short search prefers this option among the pieces compared.")
        priority = choice_recommendation(context)
        if priority and priority["uci"] != best["uci"]:
            answer = (f"Før du vælger mellem {names}, bør du undersøge {priority['san']}; den korte søgning vurderer det klart højere end de sammenlignede muligheder." if da else
                      f"Before choosing {names}, examine {priority['san']}; the short search rates it clearly above the compared options.")
        statements["piece_choice_answer"] = answer
        for index, candidate in enumerate(ranked[:2]):
            move = chess.Move.from_uci(candidate["uci"])
            facts = move_facts(board, move)
            piece_name = name(board.piece_type_at(move.from_square))
            action = ("udvikler" if facts["develops_minor"] else "flytter") if da else ("develops" if facts["develops_minor"] else "moves")
            detail = (f"{candidate['san']} {action} din {piece_name} fra {facts['from']} til {facts['to']}" if da else
                      f"{candidate['san']} {action} your {piece_name} from {facts['from']} to {facts['to']}")
            if facts["central_control"]:
                detail += (" og kontrollerer " if da else " and controls ") + ", ".join(facts["central_control"])
            if facts["legal_reply_captures"]:
                detail += ("; modstanderen har et lovligt slag på destinationsfeltet, så undersøg svaret" if da else
                           "; the opponent can legally capture on its destination, so check the reply")
            statements[f"piece_choice_{index}"] = detail + "."
        statements["piece_choice_limit"] = "Valget er et estimat fra en kort søgning i netop denne stilling." if da else "This choice is a short-search estimate for this particular position."
        if context.get("follow_up") == "why":
            focus = choice_recommendation(context) or best
            facts = move_facts(board, chess.Move.from_uci(focus["uci"]))
            piece_name = name(board.piece_type_at(chess.parse_square(facts["from"])))
            reason = (f"Pointen med {focus['san']} er at aktivere din {piece_name} fra {facts['from']} til {facts['to']}" if da else
                      f"The idea behind {focus['san']} is to activate your {piece_name} from {facts['from']} to {facts['to']}")
            if facts["central_control"]:
                reason += (" og lægge pres på centrumfelterne " if da else " and pressure the central squares ") + ", ".join(facts["central_control"])
            statements = {"piece_choice_why": reason + ".", **statements}
    else:
        choices = (" og " if da else " and ").join(name(piece) for piece in available) or names
        if available:
            statements["piece_choice_answer"] = (f"Valget her er {choices}. Jeg kan ikke rangordne mulighederne uden en fuldført motoranalyse." if da else
                f"The options here are {choices}. I cannot rank them without a completed engine analysis.")
        else:
            statements["piece_choice_answer"] = ("Ingen af mulighederne har et lovligt træk, der passer til dit spørgsmål." if da else
                                                  "Neither option has a legal move matching your question in this position.")
    if missing:
        blocked = ", ".join(name(piece) for piece in missing)
        action = ("udvikle" if request["development"] else "flytte") if da else ("develop" if request["development"] else "move")
        statements["piece_choice_blocked"] = (f"Du kan ikke lovligt {action} din {blocked} i denne stilling." if da else
            f"You cannot legally {action} your {blocked} in this position." if request["development"] else
            f"There is currently no legal move with your {blocked} in this position.")
    return statements
