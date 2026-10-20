"""Legal board operations and conservative, deterministic observations."""
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
    return {"check": board.is_check(), "exposed_pieces": exposed, "absolute_pins": pinned,
            "geometric_double_attacks": fork_patterns, "geometric_skewers": geometric_skewers(board),
            "verified_short_forks": forcing_minor_forks(board), "material": material,
            "phase": "endgame" if nonpawns <= 4 else "opening" if board.fullmove_number <= 10 else "middlegame",
            "legal_captures": [board.san(m) for m in board.legal_moves if board.is_capture(m)],
            "legal_checks": [board.san(m) for m in board.legal_moves if board.gives_check(m)]}


def move_facts(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    after = board.copy()
    after.push(move)
    central = [chess.square_name(s) for s in after.attacks(move.to_square) if s in (chess.D4, chess.E4, chess.D5, chess.E5)]
    legal_reply_captures = []
    for reply in after.legal_moves:
        if reply.to_square == move.to_square and after.is_capture(reply):
            legal_reply_captures.append(after.san(reply))
    return {"central_control": central, "legal_reply_captures": legal_reply_captures,
            "piece": chess.piece_name(piece.piece_type), "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square), "check": board.gives_check(move),
            "capture": board.is_capture(move), "captured_piece": chess.piece_name(captured.piece_type) if captured else "pawn" if board.is_en_passant(move) else None,
            "castle": board.is_castling(move), "promotion": chess.piece_name(move.promotion) if move.promotion else None,
            "develops_minor": piece.piece_type in (chess.KNIGHT, chess.BISHOP)
            and chess.square_rank(move.from_square) == (0 if piece.color else 7)}


def move_idea(facts: dict, language: str = "en") -> str:
    if language == "da":
        if facts["castle"]: return "Rokaden flytter kongen og bringer tårnet tættere på centrum."
        if facts["promotion"]: return "Bonden forvandles og giver en ny officer."
        if facts["check"]: return "Trækket giver skak, så modstanderen skal reagere."
        if facts["capture"]:
            captured = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning"}.get(facts.get("captured_piece"), "brik")
            if facts.get("legal_reply_captures"):
                return f"Trækket slår en {captured}, men modstanderen kan straks slå tilbage på {facts['to']}."
            return f"Trækket slår en {captured}, som ikke straks kan slås tilbage på {facts['to']}; du vinder materiale."
        if facts["develops_minor"]: return "Trækket udvikler en let officer fra baglinjen."
        if facts.get("central_control"): return "Trækket giver brikken kontrol over " + ", ".join(facts["central_control"]) + "."
        return "Sammenlign brikkernes aktivitet og modstanderens mulige svar."
    if facts["castle"]: return "Castling moves the king and brings a rook closer to the center."
    if facts["promotion"]: return "The pawn promotes, adding a new piece."
    if facts["check"]: return "This gives check, so the opponent must respond to the king threat."
    if facts["capture"]:
        captured = facts.get("captured_piece") or "piece"
        if facts.get("legal_reply_captures"):
            return f"This captures a {captured}, but the opponent can immediately recapture on {facts['to']}."
        return f"This captures a {captured} with no immediate legal recapture on {facts['to']}, gaining material."
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
