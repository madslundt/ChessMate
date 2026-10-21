"""Clickable explanations bound to the legal position where a threat occurs."""
import chess

from .chess_tools import move_facts, variation_evidence


BAD_MOVES = {"Inaccuracy", "Mistake", "Blunder"}
PIECES_DA = {"pawn": "Bonde", "knight": "Springer", "bishop": "Løber", "rook": "Tårn", "queen": "Dronning", "king": "Konge"}
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def bad_move_visuals(board: chess.Board, move: chess.Move, feedback: dict, language: str) -> dict:
    """Use verified captures/mate and board geometry; never rank geometric threats."""
    if (feedback.get("classification") not in BAD_MOVES or feedback.get("fen") != board.fen()
            or feedback.get("move", move.uci()) != move.uci() or move not in board.legal_moves):
        return {}
    da = language == "da"
    result = {"threats": []}
    best = feedback.get("best") or {}
    try:
        better = chess.Move.from_uci(best.get("uci", ""))
        if better != move and better in board.legal_moves:
            result["improvement"] = {"uci": better.uci(), "san": board.san(better), "fen": board.fen()}
    except ValueError:
        pass
    threats, captures, mates = [], [], []
    values = feedback.get("played", {}).get("pv_uci") or []
    if values and values[0] == move.uci():
        try:
            line = variation_evidence(board, values, identifier="bad_move_" + move.uci())
        except ValueError:
            line = None
        if line:
            replay = board.copy()
            for index, value in enumerate(line["moves"]):
                reply = chess.Move.from_uci(value)
                before, san = replay.fen(), replay.san(reply)
                opponent = replay.turn != board.turn
                victim_square = reply.to_square + (-8 if replay.turn else 8) if replay.is_en_passant(reply) else reply.to_square
                victim = replay.piece_at(victim_square) if replay.is_capture(reply) else None
                replay.push(reply)
                start, end = chess.square_name(reply.from_square), chess.square_name(reply.to_square)
                insight = {"id": f"bad_move_{move.uci()}_reply_{index}", "fen": before,
                    "claim_type": "engine_threat", "evidence_ids": [line["id"]],
                    "squares": list(dict.fromkeys([start, end, chess.square_name(victim_square)])),
                    "arrows": [{"from": start, "to": end, "color": "red"}]}
                if opponent and replay.is_checkmate():
                    king = chess.square_name(replay.king(board.turn))
                    insight.update(fen=replay.fen(), squares=[king], arrows=[], label=f"{san} · {'skakmat' if da else 'checkmate'}",
                        text=(f"I denne motorvariant giver {san} skakmat. Andre svar kan ændre forløbet." if da else
                              f"In this engine continuation, {san} delivers checkmate. Other replies may change the line."))
                    for attacker in replay.checkers():
                        insight["squares"].append(chess.square_name(attacker))
                        insight["arrows"].append({"from": chess.square_name(attacker), "to": king, "color": "red"})
                    mates.append(insight)
                elif opponent and victim and line["material_change"] < 0:
                    piece = chess.piece_name(victim.piece_type)
                    name = PIECES_DA[piece].lower() if da else piece
                    square = chess.square_name(victim_square)
                    insight.update(label=f"{san} · {name} {square}",
                        text=(f"I denne motorvariant slår {san} en {name} på {square}. Varianten giver et nettotab af materiale; andre svar kan ændre resultatet." if da else
                              f"In this engine continuation, {san} captures the {name} on {square}. The line loses material overall; other replies may change the result."))
                    captures.append((VALUES[victim.piece_type], insight))
    threats.extend(mates[:1] or [item for _, item in sorted(captures, key=lambda entry: -entry[0])[:1]])
    after = board.copy()
    after.push(move)
    facts = feedback.get("facts") or move_facts(board, move)
    for exposed in facts.get("newly_exposed_own", [])[:3]:
        if any(item["fen"] == after.fen() and exposed["square"] in item["squares"] for item in threats):
            continue
        square = chess.parse_square(exposed["square"])
        piece = after.piece_at(square)
        if piece is None or piece.color != board.turn:
            continue
        attackers = [reply for reply in after.legal_moves if reply.to_square == square and after.is_capture(reply)]
        if not attackers:
            continue
        name = PIECES_DA[chess.piece_name(piece.piece_type)] if da else chess.piece_name(piece.piece_type).capitalize()
        threats.append({"id": f"bad_move_{move.uci()}_exposed_{exposed['square']}", "fen": after.fen(),
            "claim_type": "board_geometry", "evidence_ids": ["move_" + move.uci()],
            "label": f"{name} {exposed['square']} · {'angrebet' if da else 'under attack'}",
            "text": (f"Brikken på {exposed['square']} er nu angrebet og geometrisk udækket. Et lovligt slag beviser ikke alene en materialgevinst." if da else
                     f"The piece on {exposed['square']} is now attacked and geometrically undefended. A legal capture alone does not prove a material win."),
            "squares": [exposed["square"], *dict.fromkeys(chess.square_name(reply.from_square) for reply in attackers)],
            "arrows": [{"from": chess.square_name(reply.from_square), "to": exposed["square"], "color": "red"} for reply in attackers]})
    result["threats"] = threats[:3]
    return result
