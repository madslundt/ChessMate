"""Inspectable positional evidence and qualified plans, never tactical-profit proofs."""
import chess


def strategic_facts(board: chess.Board) -> dict:
    result = {"open_files": [], "sides": {}}
    all_pawns = board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)
    result["open_files"] = [chess.FILE_NAMES[file] for file in range(8) if not any(chess.square_file(sq) == file for sq in all_pawns)]
    for color in chess.COLORS:
        own = board.pieces(chess.PAWN, color)
        enemy = board.pieces(chess.PAWN, not color)
        king = board.king(color)
        ring = board.attacks(king) if king is not None else chess.SquareSet()
        attacked_ring = [chess.square_name(sq) for sq in ring if board.is_attacked_by(not color, sq)]
        isolated, passed, backward, doubled, outposts = [], [], [], [], []
        for square in own:
            file, rank = chess.square_file(square), chess.square_rank(square)
            adjacent = [sq for sq in own if abs(chess.square_file(sq) - file) == 1]
            if not adjacent: isolated.append(chess.square_name(square))
            if not any(abs(chess.square_file(sq) - file) <= 1 and
                       (chess.square_rank(sq) > rank if color else chess.square_rank(sq) < rank) for sq in enemy):
                passed.append(chess.square_name(square))
            front = square + (8 if color else -8)
            if adjacent and 0 <= front < 64 and not board.piece_at(front):
                all_ahead = all(chess.square_rank(sq) > rank if color else chess.square_rank(sq) < rank for sq in adjacent)
                enemy_pawn_attack = any(sq in enemy for sq in board.attackers(not color, front))
                own_pawn_support = any(sq in own for sq in board.attackers(color, front))
                if all_ahead and enemy_pawn_attack and not own_pawn_support: backward.append(chess.square_name(square))
        for file in range(8):
            if sum(chess.square_file(sq) == file for sq in own) > 1: doubled.append(chess.FILE_NAMES[file])
        activity = []
        for square, piece in board.piece_map().items():
            if piece.color != color or piece.piece_type in (chess.PAWN, chess.KING): continue
            reach = [sq for sq in board.attacks(square) if board.color_at(sq) != color]
            activity.append({"square": chess.square_name(square), "piece": chess.piece_name(piece.piece_type), "reach": len(reach)})
            rank, file = chess.square_rank(square), chess.square_file(square)
            supported = any(sq in own for sq in board.attackers(color, square))
            future_challenge = any(abs(chess.square_file(sq) - file) == 1 and
                                   (chess.square_rank(sq) > rank if color else chess.square_rank(sq) < rank) for sq in enemy)
            if piece.piece_type in (chess.KNIGHT, chess.BISHOP) and (rank >= 4 if color else rank <= 3) and supported and not future_challenge:
                outposts.append(chess.square_name(square))
        shield = [chess.square_name(sq) for sq in own if king is not None and abs(chess.square_file(sq) - chess.square_file(king)) <= 1
                  and (1 <= chess.square_rank(sq) - chess.square_rank(king) <= 2 if color else
                       1 <= chess.square_rank(king) - chess.square_rank(sq) <= 2)]
        space = [chess.square_name(sq) for sq in chess.SQUARES if (chess.square_rank(sq) >= 4 if color else chess.square_rank(sq) <= 3)
                 and board.is_attacked_by(color, sq)]
        semi_open = [chess.FILE_NAMES[file] for file in range(8) if not any(chess.square_file(sq) == file for sq in own)
                     and any(chess.square_file(sq) == file for sq in enemy)]
        result["sides"]["white" if color else "black"] = {"isolated": isolated, "passed": passed,
            "backward_candidates": backward, "doubled_files": doubled, "outpost_candidates": outposts,
            "semi_open_files": semi_open, "piece_activity": activity, "space_squares": space,
            "king": chess.square_name(king) if king is not None else None, "king_ring_attacked": attacked_ring, "pawn_shield": shield}
    levers = []
    for move in board.legal_moves:
        if board.piece_type_at(move.from_square) != chess.PAWN: continue
        after = board.copy()
        after.push(move)
        contacts = [chess.square_name(sq) for sq in after.attacks(move.to_square)
                    if after.piece_type_at(sq) == chess.PAWN and after.color_at(sq) != board.turn]
        if board.is_capture(move) or contacts:
            levers.append({"uci": move.uci(), "san": board.san(move), "from": chess.square_name(move.from_square),
                           "to": chess.square_name(move.to_square), "contacts": contacts})
    result["legal_pawn_breaks"] = levers
    return result


def strategic_insights(board: chess.Board, color: chess.Color, level: str = "intermediate", language: str = "en") -> list[dict]:
    facts = strategic_facts(board)
    side = facts["sides"]["white" if color else "black"]
    da = language == "da"
    insights = []
    def add(kind, squares, en, danish, interpretation=False):
        insights.append({"id": "strategy_" + kind, "evidence_ids": ["strategy_" + kind],
            "claim_type": "strategic_interpretation" if interpretation else "position_fact", "text": danish if da else en,
            "fen": board.fen(), "squares": squares, "arrows": [], "evidence": {"feature": kind, "squares": squares}})
    if side["passed"]:
        squares = ", ".join(side["passed"])
        add("passed", side["passed"], f"Your passed pawns are on {squares}: no enemy pawn is ahead on their file or adjacent files. Consider supporting their advance, but check the king and piece blockades.",
            f"Dine fribønder står på {squares}: ingen fjendtlig bonde står foran dem på deres egen eller nabolinjerne. Overvej at støtte fremrykningen, men undersøg blokader og kongerne.")
    if side["isolated"]:
        squares = ", ".join(side["isolated"])
        add("isolated", side["isolated"], f"Your pawns on {squares} have no friendly pawn on an adjacent file. They may need piece support; isolation alone does not make a pawn weak.",
            f"Dine bønder på {squares} har ingen venlig bonde på en nabolinje. De kan have brug for officerstøtte; isolering alene gør ikke en bonde svag.")
    if level != "beginner":
        if side["doubled_files"]:
            files = ", ".join(side["doubled_files"])
            add("doubled", [], f"You have doubled pawns on the {files} files. Compare their mobility and the open lines they provide before judging the structure.",
                f"Du har dobbeltbønder på {files}-linjerne. Sammenlign deres bevægelighed og åbne linjer, før du vurderer strukturen.")
        if side["backward_candidates"]:
            squares = ", ".join(side["backward_candidates"])
            add("backward", side["backward_candidates"], f"The pawns on {squares} are backward-pawn candidates: adjacent friendly pawns are further advanced and the empty advance square is attacked by an enemy pawn without friendly pawn support. This is a structural heuristic, not proof they are lost.",
                f"Bønderne på {squares} er kandidater til tilbagestående bønder: nabobønderne er længere fremme, og fremrykningsfeltet angribes af en fjendtlig bonde uden egen bondestøtte. Det er en strukturindikator, ikke en bevist gevinst.", True)
        if side["outpost_candidates"]:
            squares = ", ".join(side["outpost_candidates"])
            add("outposts", side["outpost_candidates"], f"Your minor pieces on {squares} are pawn-supported in the enemy half, and no enemy pawn on an adjacent file can challenge them by a straight advance. These are outpost candidates; exchanges and pawn captures can still change them.",
                f"Dine lette officerer på {squares} har bondestøtte på modstanderens halvdel, og ingen fjendtlig nabobonde kan udfordre dem ved lige fremrykning. De er mulige forposter; bytter og bondeslag kan ændre billedet.", True)
        files = facts["open_files"]
        if files:
            add("open_files", [], f"The {', '.join(files)} files contain no pawns. Consider contesting an open file with a rook, after checking entry squares and exchanges.",
                f"Linjerne {', '.join(files)} indeholder ingen bønder. Overvej at bestride en åben linje med et tårn efter at have undersøgt indbrudsfelter og bytter.")
        if side["semi_open_files"]:
            files = ", ".join(side["semi_open_files"])
            add("semi_open", [], f"The {files} files are semi-open for you: only the opponent has pawns there. Assess whether those pawns can be pressured safely.",
                f"Linjerne {files} er halvåbne for dig: kun modstanderen har bønder dér. Vurder om de bønder kan angribes sikkert.")
        if side["piece_activity"]:
            piece = min(side["piece_activity"], key=lambda item: item["reach"])
            add("activity", [piece["square"]], f"The {piece['piece']} on {piece['square']} reaches {piece['reach']} squares not occupied by friendly pieces. Consider improving its scope; this geometric count does not measure legal mobility or tactical safety.",
                f"Brikken på {piece['square']} når {piece['reach']} felter uden egne brikker. Overvej at forbedre rækkevidden; tallet måler ikke lovlig bevægelighed eller taktisk sikkerhed.", True)
        add("space", side["space_squares"], f"Your pieces geometrically control {len(side['space_squares'])} squares in the enemy half. Space may help maneuvering, but overextension and exchanges still matter.",
            f"Dine brikker kontrollerer geometrisk {len(side['space_squares'])} felter på modstanderens halvdel. Plads kan hjælpe manøvrering, men overstrækning og bytter skal undersøges.", True)
    if side["king_ring_attacked"]:
        squares = ", ".join(side["king_ring_attacked"])
        add("king_safety", [side["king"], *side["king_ring_attacked"]], f"The enemy geometrically attacks these squares around your king on {side['king']}: {squares}. Check legal checks and escape squares; this alone does not prove a mating attack.",
            f"Modstanderen angriber geometrisk felterne {squares} omkring din konge på {side['king']}. Undersøg lovlige skakker og flugtfelter; det beviser ikke et matangreb.")
    if color == board.turn and facts["legal_pawn_breaks"] and level != "beginner":
        moves = facts["legal_pawn_breaks"][:3]
        add("pawn_breaks", [move["to"] for move in moves], f"Legal pawn-contact candidates include {', '.join(move['san'] for move in moves)}. Each captures or creates pawn contact. Compare the engine replies before opening the position.",
            f"Lovlige bondestød med kontakt omfatter {', '.join(move['san'] for move in moves)}. Hvert træk slår eller skaber bondekontakt. Sammenlign motorens svar, før du åbner stillingen.", True)
    return insights


def candidate_strategy(board: chess.Board, candidate: dict, language: str = "en", level: str = "intermediate") -> dict:
    move = chess.Move.from_uci(candidate["uci"])
    after = board.copy()
    after.push(move)
    before_facts, after_facts = strategic_facts(board), strategic_facts(after)
    side = "white" if board.turn else "black"
    before, changed = before_facts["sides"][side], after_facts["sides"][side]
    da = language == "da"
    effects = []
    def effect(kind, en, danish, squares, favorable=True, target_fen=None):
        effects.append({"id": f"candidate_{move.uci()}_{kind}", "evidence_ids": [f"candidate_{move.uci()}_{kind}"],
            "claim_type": "strategic_interpretation", "fen": target_fen or after.fen(), "text": danish if da else en,
            "squares": squares, "arrows": [], "favorable": favorable})
    old_ring, new_ring = len(before["king_ring_attacked"]), len(changed["king_ring_attacked"])
    if new_ring != old_ring:
        effect("prophylaxis", f"This changes the number of geometrically attacked squares around your king from {old_ring} to {new_ring}. {'Reducing this pressure is a possible prophylactic benefit' if new_ring < old_ring else 'The added pressure is a king-safety consideration'}; verify the actual checks.",
            f"Antallet af geometrisk angrebne felter omkring din konge ændres fra {old_ring} til {new_ring}. Undersøg de faktiske skakker, før du vurderer kongens sikkerhed.", changed["king_ring_attacked"], new_ring < old_ring)
    if board.piece_type_at(move.from_square) == chess.ROOK and chess.FILE_NAMES[chess.square_file(move.to_square)] in after_facts["open_files"]:
        effect("rook_file", f"The rook reaches the open {chess.FILE_NAMES[chess.square_file(move.to_square)]}-file. Consider an entry square and the opponent's contesting rook; an open file alone does not guarantee activity.",
            "Tårnet når en åben linje. Undersøg indbrudsfelter og modstanderens mulighed for at bestride linjen; en åben linje garanterer ikke aktivitet.", [chess.square_name(move.to_square)])
    if chess.square_name(move.to_square) in changed["outpost_candidates"]:
        effect("outpost", "The piece occupies a pawn-supported outpost candidate. Check exchanges before treating it as permanent.",
            "Brikken indtager en bondestøttet mulig forpost. Undersøg bytter, før du regner den som permanent.", [chess.square_name(move.to_square)])
    if board.piece_type_at(move.from_square) == chess.PAWN:
        if chess.square_name(move.to_square) in changed["passed"]:
            effect("passed", "This advances or creates a passed pawn. Coordinate its support and check blockades rather than assuming promotion.",
                "Trækket fremrykker eller skaber en fribonde. Koordinér støtten og undersøg blokader frem for at antage forvandling.", [chess.square_name(move.to_square)])
        if any(item["uci"] == move.uci() for item in before_facts["legal_pawn_breaks"]):
            effect("pawn_break", "This is a legal pawn lever: it captures or creates pawn contact. The engine continuation helps test which lines open and who can use them.",
                "Det er et lovligt bondestød: det slår eller skaber bondekontakt. Motorvarianten kan teste, hvilke linjer der åbnes, og hvem der kan bruge dem.", [chess.square_name(move.to_square)])
    before_piece = next((item for item in before["piece_activity"] if item["square"] == chess.square_name(move.from_square)), None)
    after_piece = next((item for item in changed["piece_activity"] if item["square"] == chess.square_name(move.to_square)), None)
    pawn_support = [chess.square_name(sq) for sq in after.attackers(board.turn, move.to_square) if after.piece_type_at(sq) == chess.PAWN]
    if after_piece and pawn_support:
        support_en = (f"The pawn on {pawn_support[0]} attacks {after_piece['square']}, supporting the {after_piece['piece']} geometrically. Check exchanges before assuming it is safe." if level == "beginner" else
            f"The {after_piece['piece']} on {after_piece['square']} has geometric pawn support from {', '.join(pawn_support)}. This support matters when comparing exchanges, but does not by itself prove safety or an outpost.")
        effect("pawn_support", support_en,
            f"Brikken på {after_piece['square']} har geometrisk bondestøtte fra {', '.join(pawn_support)}. Støtten er relevant ved bytter, men beviser ikke alene sikkerhed eller en forpost.", [after_piece["square"], *pawn_support])
    if before_piece and after_piece and before_piece["reach"] != after_piece["reach"]:
        activity_en = (f"From {after_piece['square']}, the {after_piece['piece']} reaches {'more' if after_piece['reach'] > before_piece['reach'] else 'fewer'} squares geometrically. Check what the opponent can attack in return." if level == "beginner" else
            f"The moved piece's geometric reach changes from {before_piece['reach']} to {after_piece['reach']} squares. This is an activity clue, not proof of tactical improvement.")
        effect("activity", activity_en,
            f"Brikkens geometriske rækkevidde ændres fra {before_piece['reach']} til {after_piece['reach']} felter. Det er et aktivitetstegn, ikke et taktisk bevis.", [after_piece["square"]], after_piece["reach"] > before_piece["reach"])
    replay = board.copy()
    captured_value = {"white": 0, "black": 0}
    piece_values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    for value in candidate.get("pv_uci", []):
        pv_move = chess.Move.from_uci(value)
        if pv_move not in replay.legal_moves: break
        if replay.is_capture(pv_move):
            victim = chess.PAWN if replay.is_en_passant(pv_move) else replay.piece_type_at(pv_move.to_square)
            captured_value["white" if replay.turn else "black"] += piece_values[victim]
        replay.push(pv_move)
    if candidate.get("pv_uci"):
        own_captures, enemy_captures = captured_value[side], captured_value["black" if board.turn else "white"]
        if own_captures and enemy_captures:
            effect("exchange", f"This particular line has captures by both sides: your side captures {own_captures} pawn units and gives up {enemy_captures}, a capture tally of {own_captures - enemy_captures:+}. This material-only comparison does not decide checkmate, compensation, or what happens against other replies.",
                f"Netop denne variant har slag fra begge sider: din side slår {own_captures} bondeenheder og afgiver {enemy_captures}, en slagbalance på {own_captures - enemy_captures:+}. Dette materialeregnskab afgør ikke mat, kompensation eller andre svar.", [],
                own_captures >= enemy_captures and not (replay.is_checkmate() and replay.turn == board.turn), replay.fen())
        initial_queens = sum(len(board.pieces(chess.QUEEN, c)) for c in chess.COLORS)
        final_queens = sum(len(replay.pieces(chess.QUEEN, c)) for c in chess.COLORS)
        if initial_queens == 2 and final_queens == 0:
            effect("queen_exchange", "Both queens are off the board at the end of this particular engine line. Compare king activity and pawn weaknesses in that queenless position; other replies may produce a different result.",
                "Begge dronninger er væk fra brættet ved slutningen af netop denne motorvariant. Sammenlign kongeaktivitet og bondesvagheder i den stilling; andre svar kan give et andet resultat.", [], True, replay.fen())
        minor_major = lambda b: sum(len(b.pieces(p, c)) for p in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in chess.COLORS)
        if minor_major(board) > 4 >= minor_major(replay):
            effect("endgame_transition", "This engine continuation reaches a position with at most four non-pawn, non-king pieces. Consider king activity and passed pawns in this endgame transition; the line is not forced merely because the engine supplies it.",
                "Denne motorvariant når en stilling med højst fire officerer ud over kongerne. Overvej kongeaktivitet og fribønder ved overgangen til slutspil; motorvarianten er ikke nødvendigvis tvungen.", [], True, replay.fen())
    return {"effects": effects, "advantages": [item["text"] for item in effects if item["favorable"]],
            "drawbacks": [item["text"] for item in effects if not item["favorable"]],
            "plan": effects[0]["text"] if effects else ("Test the opponent's forcing reply before committing to a longer plan." if not da else "Undersøg modstanderens tvingende svar, før du vælger en længere plan."),
            "qualification": "Positional considerations interpreted from explicit geometry; engine rankings do not independently prove strategic causality."}
