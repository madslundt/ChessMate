"""Legal board operations and conservative, deterministic observations."""
import re

import chess


def parse_board(fen: str, moves: list[str] | None = None) -> chess.Board:
    try:
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError("Invalid chess position")
        for move in moves or []:
            board.push(parse_move(board, move))
        return board
    except (ValueError, chess.InvalidMoveError, chess.IllegalMoveError) as exc:
        raise ValueError(f"Invalid position or variation: {exc}") from exc


def parse_move(board: chess.Board, value: str) -> chess.Move:
    try:
        move = chess.Move.from_uci(value)
        if move in board.legal_moves:
            return move
    except ValueError:
        pass
    try:
        move = board.parse_san(value)
        if move and move in board.legal_moves:
            return move
    except ValueError:
        pass
    raise ValueError("Illegal move. Use a legal UCI move (e2e4) or SAN (e4).")


def resolve_move_references(board: chess.Board, question: str) -> dict:
    """Resolve explicit notation and ordinary piece references without guessing ambiguity."""
    resolved, ambiguous = [], []
    for token_match in re.finditer(r"\S+", question):
        token = token_match.group()
        # A destination in prose is a square reference, not a standalone pawn SAN move.
        if re.search(r"\b(?:to|til|on|på)\s+$", question[:token_match.start()], flags=re.IGNORECASE):
            continue
        try:
            move = parse_move(board, token.strip(".,!?;:()[]\"'"))
            if move.uci() not in resolved: resolved.append(move.uci())
        except ValueError:
            continue
    names = {"pawn": chess.PAWN, "bonde": chess.PAWN, "knight": chess.KNIGHT, "springer": chess.KNIGHT,
             "bishop": chess.BISHOP, "løber": chess.BISHOP, "rook": chess.ROOK, "tårn": chess.ROOK,
             "queen": chess.QUEEN, "dronning": chess.QUEEN, "king": chess.KING, "konge": chess.KING}
    lower = question.lower()
    for name, piece_type in names.items():
        for match in re.finditer(r"\b" + name + r"\b(?:\s+(?:from|on|fra|på)\s+([a-h][1-8]))?\s+(?:to|til)\s+([a-h][1-8])\b", lower):
            origin, target = match.groups()
            choices = [m for m in board.legal_moves if board.piece_type_at(m.from_square) == piece_type
                       and m.to_square == chess.parse_square(target)
                       and (origin is None or m.from_square == chess.parse_square(origin))]
            if len(choices) == 1:
                if choices[0].uci() not in resolved: resolved.append(choices[0].uci())
            elif len(choices) > 1:
                ambiguous.append({"reference": match.group(), "choices": [{"uci": m.uci(), "san": board.san(m),
                    "from": chess.square_name(m.from_square), "to": chess.square_name(m.to_square)} for m in choices]})
        if re.search(r"\b(?:take|capture|slå)\s+(?:(?:that|the|den)\s+)?" + name + r"\b", lower):
            choices = [m for m in board.legal_moves if board.is_capture(m)
                       and (board.piece_type_at(m.to_square) == piece_type or
                            piece_type == chess.PAWN and board.is_en_passant(m))]
            if len(choices) == 1:
                if choices[0].uci() not in resolved: resolved.append(choices[0].uci())
            elif len(choices) > 1:
                ambiguous.append({"reference": name, "choices": [{"uci": m.uci(), "san": board.san(m),
                    "from": chess.square_name(m.from_square), "to": chess.square_name(m.to_square)} for m in choices]})
    return {"moves": resolved, "ambiguous": ambiguous}


def geometric_skewers(board: chess.Board) -> list[dict]:
    """Ray geometry only: a more valuable enemy is in front of a less valuable enemy."""
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
    result = []
    for square, piece in board.piece_map().items():
        directions = []
        if piece.piece_type in (chess.ROOK, chess.QUEEN): directions += [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if piece.piece_type in (chess.BISHOP, chess.QUEEN): directions += [(1, 1), (-1, 1), (1, -1), (-1, -1)]
        for df, dr in directions:
            file, rank = chess.square_file(square) + df, chess.square_rank(square) + dr
            targets = []
            while 0 <= file < 8 and 0 <= rank < 8:
                target_square = chess.square(file, rank)
                target = board.piece_at(target_square)
                if target:
                    if target.color == piece.color: break
                    targets.append((target_square, target))
                    if len(targets) == 2: break
                file, rank = file + df, rank + dr
            if len(targets) == 2 and values[targets[0][1].piece_type] > values[targets[1][1].piece_type]:
                result.append({"attacker": chess.square_name(square), "front": chess.square_name(targets[0][0]),
                               "behind": chess.square_name(targets[1][0]), "meaning": "geometric skewer; tactical profitability unverified"})
    return result


def forcing_minor_forks(board: chess.Board) -> list[dict]:
    """Verify a narrow motif: a checking minor/pawn fork keeps a legal queen capture after EVERY legal reply.

    This proves the short forcing pattern, not the outcome of all longer tactics.
    """
    result = []
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        if piece.piece_type not in (chess.PAWN, chess.KNIGHT, chess.BISHOP) or not board.gives_check(move): continue
        after = board.copy()
        after.push(move)
        queens = [sq for sq in after.attacks(move.to_square)
                  if after.piece_type_at(sq) == chess.QUEEN and after.color_at(sq) != piece.color]
        if not queens: continue
        replies = list(after.legal_moves)
        if not replies: continue
        verified = True
        for reply in replies:
            # A reply that takes another major piece may offset the apparent gain.
            captured = after.piece_at(reply.to_square)
            if captured and captured.piece_type in (chess.QUEEN, chess.ROOK):
                verified = False
                break
            continuation = after.copy()
            continuation.push(reply)
            captures = [m for m in continuation.legal_moves if m.from_square == move.to_square
                        and continuation.piece_type_at(m.to_square) == chess.QUEEN
                        and continuation.color_at(m.to_square) != piece.color]
            if not captures:
                verified = False
                break
        if verified:
            result.append({"uci": move.uci(), "san": board.san(move), "targets": [chess.square_name(sq) for sq in queens],
                           "verified_replies": len(replies), "meaning": "checking fork with a legal queen capture after every immediate reply; longer tactics unverified"})
    return result


def observations(board: chess.Board) -> dict:
    exposed, pinned, fork_patterns = [], [], []
    for square, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        enemies = board.attackers(not piece.color, square)
        defenders = board.attackers(piece.color, square)
        info = {"square": chess.square_name(square), "piece": chess.piece_name(piece.piece_type),
                "color": "white" if piece.color else "black"}
        if enemies and not defenders:
            exposed.append({**info, "attackers": [chess.square_name(x) for x in enemies],
                            "meaning": "attacked and geometrically undefended; not proof of a winning capture"})
        if board.is_pinned(piece.color, square):
            pinned.append(info)
        targets = [x for x in board.attacks(square) if board.piece_at(x)
                   and board.color_at(x) != piece.color
                   and board.piece_type_at(x) in (chess.KING, chess.QUEEN, chess.ROOK)]
        if len(targets) >= 2:
            fork_patterns.append({**info, "targets": [chess.square_name(x) for x in targets],
                                  "meaning": "geometric double attack; profitability unverified"})
    material = {"white": 0, "black": 0}
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    for piece in board.piece_map().values():
        material["white" if piece.color else "black"] += values[piece.piece_type]
    nonpawns = sum(len(board.pieces(t, c)) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in chess.COLORS)
    pawn_structure = {"white": {"isolated": [], "passed": [], "doubled_files": []},
                      "black": {"isolated": [], "passed": [], "doubled_files": []}}
    for color in chess.COLORS:
        own, enemy = board.pieces(chess.PAWN, color), board.pieces(chess.PAWN, not color)
        structure = pawn_structure["white" if color else "black"]
        for square in own:
            file, rank = chess.square_file(square), chess.square_rank(square)
            if not any(abs(chess.square_file(other) - file) == 1 for other in own):
                structure["isolated"].append(chess.square_name(square))
            if not any(abs(chess.square_file(other) - file) <= 1 and
                       (chess.square_rank(other) > rank if color else chess.square_rank(other) < rank) for other in enemy):
                structure["passed"].append(chess.square_name(square))
        structure["doubled_files"] = [chess.FILE_NAMES[file] for file in range(8)
                                       if sum(chess.square_file(sq) == file for sq in own) > 1]
    open_files = [chess.FILE_NAMES[file] for file in range(8)
                  if not any(board.piece_type_at(chess.square(file, rank)) == chess.PAWN for rank in range(8))]
    return {"check": board.is_check(), "exposed_pieces": exposed, "absolute_pins": pinned,
            "geometric_double_attacks": fork_patterns, "geometric_skewers": geometric_skewers(board),
            "verified_short_forks": forcing_minor_forks(board), "material": material,
            "pawn_structure": pawn_structure, "open_files": open_files,
            "phase": "endgame" if nonpawns <= 4 else "opening" if board.fullmove_number <= 10 else "middlegame",
            "legal_captures": [board.san(m) for m in board.legal_moves if board.is_capture(m)],
            "legal_checks": [board.san(m) for m in board.legal_moves if board.gives_check(m)]}


def variation_evidence(board: chess.Board, moves: list[str], label: str = "Engine continuation", identifier: str = "line") -> dict:
    """Replay a complete legal line and bind every frame to its exact position."""
    replay, frames, sequence = board.copy(), [], []
    before = observations(board)["material"]
    for value in moves[:24]:
        move = parse_move(replay, value)
        frame = {"before_fen": replay.fen(), "uci": move.uci(), "san": replay.san(move),
                 "from": chess.square_name(move.from_square), "to": chess.square_name(move.to_square)}
        replay.push(move)
        frame["fen"] = replay.fen()
        frames.append(frame)
        sequence.append(move.uci())
    after = observations(replay)["material"]
    own, other = ("white", "black") if board.turn else ("black", "white")
    outcome = replay.outcome(claim_draw=True)
    return {"id": identifier, "label": label, "base_fen": board.fen(), "moves": sequence, "frames": frames,
            "resulting_fen": replay.fen(), "material_change": (after[own] - after[other]) - (before[own] - before[other]),
            "terminal": outcome.termination.name.lower() if outcome else None,
            "winner": ("white" if outcome.winner else "black") if outcome and outcome.winner is not None else None,
            "perspective": own, "qualification": "One legal engine continuation; other replies may change the result."}


def move_insights(board: chess.Board, candidate: dict, language: str = "en") -> tuple[list[dict], list[dict]]:
    """Position-specific evidence for text and visual coaching; no unproved tactical gains."""
    move = parse_move(board, candidate["uci"])
    facts = move_facts(board, move)
    identifier = "move_" + move.uci()
    insights = [{"id": identifier, "evidence_ids": [identifier], "claim_type": "legal_move",
        "text": f"{board.san(move)}: {move_idea(facts, language)}", "fen": board.fen(),
        "squares": [facts["from"], facts["to"]], "arrows": [{"from": facts["from"], "to": facts["to"], "color": "green"}]}]
    after_move = board.copy()
    after_move.push(move)
    if detail := relation_idea(facts, language):
        targets = facts.get("created_geometric_double_attack") or facts.get("new_absolute_pins") or facts.get("added_geometric_support", [])
        squares = [target["square"] for target in targets]
        insights.append({"id": identifier + "_geometry", "evidence_ids": [identifier], "claim_type": "board_geometry",
            "text": detail, "fen": after_move.fen(), "squares": squares,
            "arrows": [{"from": facts["to"], "to": square, "color": "blue"} for square in squares
                       if chess.parse_square(square) in after_move.attacks(move.to_square)]})
    if facts.get("newly_exposed_own"):
        squares = [target["square"] for target in facts["newly_exposed_own"]]
        insights.append({"id": identifier + "_exposed", "evidence_ids": [identifier], "claim_type": "board_geometry",
            "text": (f"Efter trækket er {', '.join(squares)} nyligt angrebet og geometrisk udækket. Det beviser ikke en vundet brik." if language == "da" else
                     f"After this move, {', '.join(squares)} newly becomes attacked and geometrically undefended. This does not prove a winning capture."),
            "fen": after_move.fen(), "squares": squares,
            "arrows": [{"from": chess.square_name(attacker), "to": square, "color": "red"} for square in squares
                       for attacker in after_move.attackers(after_move.turn, chess.parse_square(square))]})
    variations = []
    if candidate.get("pv_uci"):
        variation = variation_evidence(board, candidate["pv_uci"], board.san(move), "pv_" + move.uci())
        variations.append(variation)
        if len(variation["frames"]) > 1:
            reply = variation["frames"][1]
            insights.append({"id": identifier + "_reply", "evidence_ids": [variation["id"]], "claim_type": "engine_estimate",
                "text": (f"I denne søgning svarer modstanderen med {reply['san']}." if language == "da" else
                         f"In this search, the opponent's reply is {reply['san']}."), "fen": reply["before_fen"],
                "squares": [reply["from"], reply["to"]], "arrows": [{"from": reply["from"], "to": reply["to"], "color": "red"}]})
        delta = variation["material_change"]
        if variation["terminal"]:
            side = variation["winner"]
            text = (f"Denne variant ender med skakmat; {side} vinder." if language == "da" else
                    f"This continuation ends in checkmate; {side.capitalize()} wins.") if side else (
                    f"Denne variant ender remis ({variation['terminal']})." if language == "da" else
                    f"This continuation ends in a draw ({variation['terminal']}).")
            insights.insert(1, {"id": identifier + "_outcome", "evidence_ids": [variation["id"]], "claim_type": "terminal_line",
                "text": text, "fen": variation["resulting_fen"], "squares": [], "arrows": []})
        elif delta:
            insights.append({"id": identifier + "_material", "evidence_ids": [variation["id"]], "claim_type": "line_material",
                "text": (f"Ved slutningen af netop denne variant ændres materialebalancen med {delta:+} bondeenheder; andre svar kan ændre resultatet." if language == "da" else
                         f"At the end of this specific continuation, the material balance changes by {delta:+} pawn units; other replies may change the result."),
                "fen": variation["resulting_fen"], "squares": [], "arrows": []})
    return insights, variations


def relation_changes(board: chess.Board, after: chess.Board, move: chess.Move) -> dict:
    """Direct before/after geometry, kept separate from tactical-profit claims."""
    color = board.turn
    newly_exposed, new_pins, removed_pins, supported, lost_support = [], [], [], [], []
    old_attacks, new_attacks = board.attacks(move.from_square), after.attacks(move.to_square)
    for square, piece in after.piece_map().items():
        if piece.piece_type == chess.KING: continue
        origin = move.from_square if square == move.to_square else square
        previous = board.piece_at(origin)
        same = previous is not None and previous.color == piece.color
        info = {"square": chess.square_name(square), "piece": chess.piece_name(piece.piece_type),
                "color": "white" if piece.color else "black"}
        was_pinned = same and board.is_pinned(piece.color, origin)
        is_pinned = after.is_pinned(piece.color, square)
        if is_pinned and not was_pinned: new_pins.append(info)
        if was_pinned and not is_pinned: removed_pins.append(info)
        if piece.color != color: continue
        was_exposed = same and board.is_attacked_by(not color, origin) and not board.is_attacked_by(color, origin)
        if after.is_attacked_by(not color, square) and not after.is_attacked_by(color, square) and not was_exposed:
            newly_exposed.append(info)
        if square != move.to_square and square in new_attacks and square not in old_attacks:
            supported.append(info)
        if square != move.to_square and square in old_attacks and square not in new_attacks:
            lost_support.append(info)
    targets = [{"square": chess.square_name(square), "piece": chess.piece_name(after.piece_type_at(square))}
               for square in new_attacks if after.piece_at(square) and after.color_at(square) != color
               and after.piece_type_at(square) in (chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)]
    previous_targets = {square for square in old_attacks if board.piece_at(square) and board.color_at(square) != color}
    double_attack = targets if len(targets) >= 2 and any(chess.parse_square(target["square"]) not in previous_targets for target in targets) else []
    old_skewers = {(item["attacker"], item["front"], item["behind"]) for item in geometric_skewers(board)}
    skewers = [item for item in geometric_skewers(after) if after.color_at(chess.parse_square(item["attacker"])) == color
               and (item["attacker"], item["front"], item["behind"]) not in old_skewers]
    return {"newly_exposed_own": newly_exposed, "new_absolute_pins": new_pins, "removed_absolute_pins": removed_pins,
            "added_geometric_support": supported, "removed_geometric_support": lost_support,
            "created_geometric_double_attack": double_attack, "created_geometric_skewers": skewers}


def relation_idea(facts: dict, language: str = "en") -> str:
    da = language == "da"
    if facts.get("created_geometric_double_attack"):
        targets = ", ".join(item["square"] for item in facts["created_geometric_double_attack"])
        return (f"Fra {facts['to']} angriber brikken samtidig {targets}. Det er et geometrisk dobbeltangreb; en gevinst skal stadig verificeres." if da else
                f"From {facts['to']}, the piece attacks {targets} at the same time. This is a geometric double attack; a material win still needs verification.")
    if facts.get("created_geometric_skewers"):
        item = facts["created_geometric_skewers"][0]
        return (f"Brikken på {item['attacker']} står på linje med {item['front']} og {item['behind']}: en geometrisk spidning. Gevinsten er ikke bevist." if da else
                f"The piece on {item['attacker']} lines up with {item['front']} and {item['behind']}: a geometric skewer. A tactical win is not established.")
    if facts.get("new_absolute_pins"):
        return " ".join(f"Brikken på {item['square']} er nu bundet til sin konge." if da else
                        f"The {item['piece']} on {item['square']} is now absolutely pinned to its king."
                        for item in facts["new_absolute_pins"][:2])
    if facts.get("removed_absolute_pins"):
        squares = ", ".join(item["square"] for item in facts["removed_absolute_pins"])
        return (f"Trækket ophæver bindingen til kongen for brikken på {squares}." if da else
                f"This move removes the absolute pin to the king of the piece on {squares}.")
    if facts.get("added_geometric_support"):
        squares = ", ".join(item["square"] for item in facts["added_geometric_support"][:3])
        return (f"Fra {facts['to']} giver brikken ny geometrisk støtte til {squares}. Det beviser ikke taktisk sikkerhed." if da else
                f"From {facts['to']}, the piece adds geometric support to {squares}. This does not establish tactical safety.")
    return ""


def move_facts(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    en_passant = board.is_en_passant(move)
    capture_square = move.to_square + (-8 if board.turn else 8) if en_passant else move.to_square
    captured = board.piece_at(capture_square)
    after = board.copy()
    after.push(move)
    central = [chess.square_name(s) for s in after.attacks(move.to_square) if s in (chess.D4, chess.E4, chess.D5, chess.E5)]
    legal_reply_captures = []
    for reply in after.legal_moves:
        ep_victim = reply.to_square + (-8 if after.turn else 8) if after.is_en_passant(reply) else None
        if after.is_capture(reply) and (reply.to_square == move.to_square or ep_victim == move.to_square):
            legal_reply_captures.append(after.san(reply))
    pinned_recapturers = [chess.square_name(square) for square in after.attackers(after.turn, move.to_square)
                         if after.is_pinned(after.turn, square)
                         and not any(reply.from_square == square and reply.to_square == move.to_square for reply in after.legal_moves)]
    queen_stalemates = False
    if move.promotion and move.promotion != chess.QUEEN:
        queen = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
        if queen in board.legal_moves:
            queen_board = board.copy()
            queen_board.push(queen)
            queen_stalemates = queen_board.is_stalemate() and not after.is_stalemate()
    return {**relation_changes(board, after, move), "central_control": central, "legal_reply_captures": legal_reply_captures,
            "pinned_recapturers": pinned_recapturers, "checkmate": after.is_checkmate(),
            "stalemate": after.is_stalemate(), "underpromotion_avoids_stalemate": queen_stalemates,
            "piece": chess.piece_name(piece.piece_type), "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square), "check": board.gives_check(move),
            "en_passant": en_passant, "captured_square": chess.square_name(capture_square) if captured else None,
            "capture": board.is_capture(move), "captured_piece": chess.piece_name(captured.piece_type) if captured else "pawn" if board.is_en_passant(move) else None,
            "castle": board.is_castling(move), "promotion": chess.piece_name(move.promotion) if move.promotion else None,
            "develops_minor": piece.piece_type in (chess.KNIGHT, chess.BISHOP)
            and chess.square_rank(move.from_square) == (0 if piece.color else 7)}


def move_idea(facts: dict, language: str = "en") -> str:
    if language == "da":
        if facts.get("checkmate"): return "Trækket sætter modstanderens konge skakmat."
        if facts.get("stalemate"): return "Trækket giver pat: modstanderen har ingen lovlige træk og står ikke i skak. Partiet er remis."
        if facts.get("en_passant"):
            return (f"En passant: bonden går fra {facts['from']} til {facts['to']} og fjerner modstanderens bonde på {facts['captured_square']}. " +
                    ("Trækket giver også skak. " if facts["check"] else "") + "Undersøg modstanderens svar, før du regner materialet som vundet.")
        if facts["castle"]: return "Rokaden flytter kongen og bringer tårnet tættere på centrum."
        if facts.get("underpromotion_avoids_stalemate"): return "Underforvandlingen undgår den pat, som en forvandling til dronning ville give."
        if facts["promotion"]: return "Bonden forvandles og giver en ny officer."
        if facts["check"]: return "Trækket giver skak, så modstanderen skal reagere. " + relation_idea(facts, language)
        if facts["capture"]:
            captured = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning"}.get(facts.get("captured_piece"), "brik")
            if facts.get("legal_reply_captures"):
                return f"Trækket slår en {captured}, men modstanderen kan straks slå tilbage på {facts['to']}."
            if facts.get("pinned_recapturers"):
                return f"Trækket slår en {captured}. Forsvareren på {', '.join(facts['pinned_recapturers'])} er bundet til kongen og kan ikke lovligt slå tilbage på {facts['to']}. Andre taktiske følger skal stadig undersøges."
            return f"Trækket slår en {captured} uden et øjeblikkeligt lovligt genslag på {facts['to']}. Undersøg modstanderens andre trusler, før du regner materialet som vundet."
        if detail := relation_idea(facts, language): return detail
        if facts["develops_minor"]: return "Trækket udvikler en let officer fra baglinjen."
        if facts.get("central_control"): return "Trækket giver brikken kontrol over " + ", ".join(facts["central_control"]) + "."
        return "Sammenlign brikkernes aktivitet og modstanderens mulige svar."
    if facts.get("checkmate"): return "This move checkmates the opponent's king."
    if facts.get("stalemate"): return "This causes stalemate: the opponent has no legal move and is not in check. The game is drawn."
    if facts.get("en_passant"):
        return (f"En passant: the pawn moves from {facts['from']} to {facts['to']} and removes the opponent's pawn on {facts['captured_square']}. " +
                ("This also gives check. " if facts["check"] else "") + "Check the opponent's reply before treating the material as won.")
    if facts["castle"]: return "Castling moves the king and brings a rook closer to the center."
    if facts.get("underpromotion_avoids_stalemate"): return "Underpromoting avoids the stalemate that promotion to a queen would cause."
    if facts["promotion"]: return "The pawn promotes, adding a new piece."
    if facts["check"]: return "This gives check, so the opponent must respond to the king threat. " + relation_idea(facts, language)
    if facts["capture"]:
        captured = facts.get("captured_piece") or "piece"
        if facts.get("legal_reply_captures"):
            return f"This captures a {captured}, but the opponent can immediately recapture on {facts['to']}."
        if facts.get("pinned_recapturers"):
            return f"This captures a {captured}. The defender on {', '.join(facts['pinned_recapturers'])} is pinned to its king and cannot legally recapture on {facts['to']}. Other tactical consequences still need checking."
        return f"This captures a {captured} with no immediate legal recapture on {facts['to']}. Check the opponent's other threats before treating the material as won."
    if detail := relation_idea(facts, language): return detail
    if facts["develops_minor"]: return "This develops a minor piece from its starting rank."
    if facts.get("central_control"): return "The moved piece controls " + ", ".join(facts["central_control"]) + "."
    return "Compare piece activity and the opponent's strongest reply."


def get_position(board: chess.Board) -> dict:
    """Read an independent position snapshot; never alters the board."""
    return {"fen": board.fen(), "turn": "white" if board.turn else "black", "check": board.is_check(),
            "result": board.result(claim_draw=True), "phase": observations(board)["phase"]}


def get_legal_moves(board: chess.Board) -> list[dict]:
    return [{"uci": move.uci(), "san": board.san(move), "facts": move_facts(board, move)} for move in board.legal_moves]


def analyze_position(board: chess.Board, **budget) -> dict:
    from .engine import engine_service
    return engine_service.analyze(board.copy(), **budget)


def get_top_moves(board: chess.Board, **budget) -> list[dict]:
    return analyze_position(board, **{**budget, "candidates": 3})["candidates"]


def evaluate_candidate_move(board: chess.Board, move: str, **budget) -> dict:
    from .engine import score_number
    candidate = parse_move(board, move)
    selected = analyze_position(board, **{**budget, "candidates": 1, "root_moves": [candidate]})["candidates"]
    top = analyze_position(board, **{**budget, "candidates": 3})["candidates"]
    if not selected or not top: raise ValueError("Position has ended")
    return {"fen": board.fen(), "perspective": "white" if board.turn else "black", "candidate": selected[0],
            "best": top[0], "loss_cp": max(0, score_number(top[0]) - score_number(selected[0]))}


def analyze_variation(board: chess.Board, moves: list[str], **budget) -> dict:
    variation = board.copy()
    sequence = []
    for value in moves:
        move = parse_move(variation, value)
        sequence.append({"uci": move.uci(), "san": variation.san(move), "before_fen": variation.fen()})
        variation.push(move)
    return {"base_fen": board.fen(), "fen": variation.fen(), "moves": sequence,
            "analysis": analyze_position(variation, **budget)}


def get_threats(board: chess.Board) -> dict:
    facts = observations(board)
    return {"fen": board.fen(), "side_to_move": "white" if board.turn else "black",
            "legal_checks": facts["legal_checks"], "legal_captures": facts["legal_captures"],
            "exposed_pieces": facts["exposed_pieces"], "absolute_pins": facts["absolute_pins"],
            "verified_short_forks": facts["verified_short_forks"],
            "qualification": "Legal forcing moves and board geometry; geometric attacks alone do not prove a winning tactic."}


def get_move_history(board: chess.Board) -> list[dict]:
    replay = board.root()
    history = []
    for move in board.move_stack:
        history.append({"uci": move.uci(), "san": replay.san(move), "before_fen": replay.fen()})
        replay.push(move)
        history[-1]["fen"] = replay.fen()
    return history
