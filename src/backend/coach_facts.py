"""Bilingual, evidence-backed statements and question-aware deterministic teaching."""
import chess

from .chess_tools import move_facts, move_idea, observations, parse_move
from .engine import score_number

PIECES_DA = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning", "king": "konge"}


def review_requested(context: dict) -> bool:
    question = context["question"].lower()
    return any(term in question for term in ("so far", "my moves", "how am i", "how have i", "how did i",
        "review my", "my play", "mine træk", "indtil nu", "hvordan har jeg", "mit spil"))


def reveal_requested(context: dict) -> bool:
    question = context["question"].lower()
    if any(word in question for word in ("without revealing", "no spoilers", "uden at afsløre")): return False
    return bool(context.get("requested_candidates")) or any(word in question for word in (
        "best", "answer", "reveal", "candidate", "recommend", "compare", "better than", "bedste", "svaret", "vis træ", "anbefal", "sammenlign", "bedre end"))


def visible_candidates(context: dict, reveal: bool) -> list[dict]:
    if not reveal: return []
    question = context["question"].lower()
    requested = context.get("requested_candidates", [])
    reveal_all = not context["preferences"].get("hide_best_moves", True) or any(word in question for word in (
        "best", "answer", "reveal", "candidate", "recommend", "compare", "better than", "bedste", "svaret", "anbefal", "sammenlign", "bedre end"))
    combined = requested + (context["analysis"].get("candidates", []) if reveal_all else [])
    unique = {}
    for candidate in combined: unique.setdefault(candidate["uci"], candidate)
    return list(unique.values())[:5]


def show_line(context: dict) -> bool:
    return context["preferences"].get("show_pv", False) or any(word in context["question"].lower() for word in (
        "what happens", "what if", "calculate", "variation", "line", "hvad sker", "hvis", "fortsættelse"))


def learner_color(board: chess.Board, context: dict) -> chess.Color:
    game = context.get("game") or {}
    if game.get("mode") != "analysis" and game.get("player_color") in ("white", "black"):
        return game["player_color"] == "white"
    return board.turn


def side_name(color: chess.Color, da: bool) -> str:
    return ("Hvid" if color else "Sort") if da else ("White" if color else "Black")


def candidate_idea(board: chess.Board, move: chess.Move, language: str, learner: chess.Color) -> str:
    idea = move_idea(move_facts(board, move), language)
    if board.turn != learner:
        root, other = side_name(board.turn, language == "da"), side_name(not board.turn, language == "da")
        if language == "da":
            idea = idea.replace("giver dig", f"giver {root}").replace("modstanderens", other + "s").replace("modstanderen", other)
        else:
            idea = idea.replace("your king", root + "'s king").replace("the opponent's", other + "'s").replace("opponent's", other + "'s").replace("the opponent", other)
    return idea


def castle_statement(board: chess.Board, da: bool, learner: chess.Color | None = None) -> str:
    if learner is not None and board.turn != learner:
        root, own = side_name(board.turn, da), side_name(learner, da)
        return (f"Det er {root}s tur; vurder {own}s mulighed for rokade igen efter svaret." if da else
                f"It is {root}'s turn; reassess {own}'s castling after the reply.")
    castles = [board.san(m) for m in board.legal_moves if board.is_castling(m)]
    if castles:
        moves = ", ".join(castles)
        return (f"Du kan lovligt rokere med {moves}. Kongens rute er lovlig nu; det beviser ikke, at rokade er det bedste træk." if da else
                f"Castling is legal now with {moves}. The king's route is legally safe now; that alone does not prove castling is the best move.")
    if board.is_check():
        return "Du kan ikke rokere ud af skak." if da else "You cannot castle out of check. Resolve the check first."
    if not board.has_castling_rights(board.turn):
        return "Du har ikke længere rokaderet i denne stilling." if da else "You have no castling rights in this position."
    rank = 0 if board.turn else 7
    blockers = []
    if board.has_kingside_castling_rights(board.turn):
        blockers.extend(chess.square_name(chess.square(f, rank)) for f in (5, 6) if board.piece_at(chess.square(f, rank)))
    if board.has_queenside_castling_rights(board.turn):
        blockers.extend(chess.square_name(chess.square(f, rank)) for f in (1, 2, 3) if board.piece_at(chess.square(f, rank)))
    if blockers:
        return ("Rokade er ikke lovlig nu; der står brikker på rokaderuten: " if da else
                "Castling is not legal now; pieces occupy the castling routes on ") + ", ".join(blockers) + "."
    return ("Rokade er ikke lovlig nu, fordi kongens rute ikke er lovligt sikker." if da else
            "Castling is not legal now because the king's route is not legally safe.")


def build_statements(board: chess.Board, context: dict, language: str, reveal: bool) -> dict[str, str]:
    da = language == "da"
    evidence = context["analysis"].get("observations") or observations(board)
    phase = evidence["phase"]
    learner = learner_color(board, context)
    learner_turn = board.turn == learner
    root_name, own_name = side_name(board.turn, da), side_name(learner, da)
    statements = {
        "habit": "Undersøg skakker, slag og trusler for begge sider, før du flytter." if da else
                 "Before moving, check forcing moves for both sides: checks, captures, and threats.",
        "question": "Hvilken af dine brikker kan du forbedre uden at svække kongens sikkerhed?" if da else
                    "Which piece could you improve without weakening your king's safety?",
        "uncertainty": "Analysen er et estimat fra en kort søgning; undersøg fortsættelsen på brættet." if da else
                       "This is a short-search estimate. Test the continuation on the board before drawing conclusions.",
        "castle": castle_statement(board, da, learner),
    }
    statements["plan"] = ({"opening": "Overvej centrum, udvikling af lette officerer og kongens sikkerhed.",
                           "middlegame": "Find modstanderens trusler, og vælg derefter en brik, du kan forbedre.",
                           "endgame": "Undersøg kongernes aktivitet og mulighederne for at fremme bønder."}[phase] if da else
                          {"opening": "Consider the center, minor-piece development, and king safety.",
                           "middlegame": "Identify the opponent's threats, then look for a piece you can improve.",
                           "endgame": "Consider king activity and pawn promotion opportunities."}[phase])
    if not learner_turn:
        statements["turn"] = (f"Det er {root_name}s tur. Du spiller {own_name}; vurder stillingen igen efter modstanderens svar." if da else
                              f"It is {root_name}'s turn. You are playing {own_name}; reassess the position after the opponent's reply.")
        statements["question"] = (f"Hvad bør du undersøge for {own_name}, når {root_name} har svaret?" if da else
                                  f"What should you reassess for {own_name} after {root_name}'s reply?")
    if board.is_check():
        if learner_turn:
            statements["check"] = "Du står i skak. Dit næste træk skal ophæve skakken." if da else "You are in check. Your next move must resolve the check."
            statements["question"] = "Kan du slå den skakgivende brik, dække skakken eller flytte kongen lovligt?" if da else "Can you capture the checking piece, block the check, or legally move your king?"
        else:
            statements["check"] = (f"{root_name} står i skak og skal ophæve skakken." if da else f"{root_name} is in check and must resolve it.")
            statements["question"] = (f"Kan {root_name} slå den skakgivende brik, dække skakken eller flytte kongen lovligt?" if da else
                                      f"Can {root_name} capture the checking piece, block the check, or legally move the king?")
    if board.is_game_over(claim_draw=True):
        statements["terminal"] = ("Stillingen er afsluttet: " if da else "The position has ended: ") + board.result(claim_draw=True)
    own = "white" if learner else "black"
    own_exposed = [p for p in evidence["exposed_pieces"] if p["color"] == own]
    for index, piece in enumerate(own_exposed[:6]):
        statements[f"exposed_{index}"] = (f"Din {PIECES_DA[piece['piece']]} på {piece['square']} er angrebet og geometrisk udækket. Undersøg om modstanderen faktisk kan slå den sikkert." if da else
            f"Your {piece['piece']} on {piece['square']} is attacked and geometrically undefended. Check whether the opponent can actually capture it safely.")
    for index, piece in enumerate(own_exposed[:6]):
        attackers = []
        for square in piece["attackers"]:
            attacker = board.piece_at(chess.parse_square(square))
            name = chess.piece_name(attacker.piece_type)
            attackers.append(f"{PIECES_DA[name] if da else name} {square}")
        if attackers:
            statements[f"attackers_{index}"] = ("De geometriske angribere er: " if da else "The geometric attackers are: ") + ", ".join(attackers) + "."
        question = context["question"].lower()
        if piece["piece"] in question or PIECES_DA[piece["piece"]] in question:
            statements["recognition"] = (f"Ja, din {PIECES_DA[piece['piece']]} på {piece['square']} er angrebet og udækket." if da else
                f"Yes, your {piece['piece']} on {piece['square']} is attacked and undefended.")
    if own_exposed:
        if learner_turn:
            statements["question"] = (f"Hvordan kan du beskytte brikken på {own_exposed[0]['square']} eller skabe en stærkere trussel?" if da else
                                      f"How could you protect the piece on {own_exposed[0]['square']} or create a stronger threat?")
    elif not board.is_check():
        statements["no_exposed"] = "Ingen af dine officerer eller bønder er både angrebet og geometrisk udækkede lige nu." if da else "None of your non-king pieces is both attacked and geometrically undefended right now."
    for index, piece in enumerate(evidence["absolute_pins"][:4]):
        statements[f"pin_{index}"] = (f"Brikken på {piece['square']} er bundet til kongen." if da else
            f"The {piece['piece']} on {piece['square']} is absolutely pinned to its king.")
    attacked = []
    for square, piece in board.piece_map().items():
        if piece.color != learner or piece.piece_type == chess.KING: continue
        if board.is_attacked_by(not learner, square):
            defenders = [chess.square_name(sq) for sq in board.attackers(learner, square)]
            if defenders:
                attacked.append((chess.square_name(square), defenders))
    if attacked:
        square, defenders = attacked[0]
        statements["defended_attack"] = (f"Brikken på {square} er angrebet, men dækkes geometrisk fra {', '.join(defenders)}. Undersøg bindinger og bytter, før du regner den som sikker." if da else
            f"The piece on {square} is attacked and geometrically defended from {', '.join(defenders)}. Check pins and exchanges before assuming it is safe.")
    controlled = [chess.square_name(sq) for sq in (chess.D4, chess.E4, chess.D5, chess.E5) if board.is_attacked_by(learner, sq)]
    if controlled:
        statements["center"] = ("Dine brikker kontrollerer geometrisk disse centrumfelter: " if da else "Your pieces geometrically control these central squares: ") + ", ".join(controlled) + "."
    if context.get("unavailable_piece_choices"):
        names = [PIECES_DA[name] if da else name for name in context["unavailable_piece_choices"]]
        if learner_turn:
            statements["unavailable_piece"] = ("Der er intet lovligt træk i denne stilling med: " if da else "There is currently no legal move with your ") + ", ".join(names) + "."
        else:
            statements["unavailable_piece"] = (f"{root_name} har intet lovligt træk i denne stilling med: " if da else f"There is currently no legal {root_name} move with a ") + ", ".join(names) + "."
    candidates = visible_candidates(context, reveal)
    for index, candidate in enumerate(candidates):
        move = parse_move(board, candidate["uci"])
        prefix = "" if learner_turn else (f"For {root_name}: ")
        statements[f"candidate_{index}"] = f"{prefix}{candidate['san']}: {candidate_idea(board, move, language, learner)}"
        if show_line(context) and candidate.get("pv_uci"):
            replay, sequence = board.copy(), []
            for value in candidate["pv_uci"][:5]:
                pv_move = parse_move(replay, value)
                sequence.append(replay.san(pv_move))
                replay.push(pv_move)
            statements[f"line_{index}"] = ("En verificeret lovlig motorfortsættelse er: " if da else "One verified legal engine continuation is: ") + " ".join(sequence) + "."
            before = evidence["material"]
            after = observations(replay)["material"]
            opponent = "black" if learner else "white"
            change = (after[own] - after[opponent]) - (before[own] - before[opponent])
            if change:
                statements[f"consequence_{index}"] = (f"Ved slutningen af netop denne variant ændres din materielle balance med {change:+} bondeenheder. Det er ikke en garanti for alle svar." if da else
                    f"At the end of this specific line, your material balance changes by {change:+} pawn units. This does not guarantee the same result against every reply.")
    if len(candidates) >= 2:
        first, second = candidates[:2]
        if abs(score_number(first) - score_number(second)) <= 35:
            statements["comparison"] = (f"{first['san']} og {second['san']} ligger tæt i denne korte søgning. Der er ikke belæg for at påstå en stor kvalitetsforskel." if da else
                f"{first['san']} and {second['san']} are close in this short search. There is no evidence of a large quality difference.")
        else:
            stronger, weaker = sorted((first, second), key=score_number, reverse=True)
            statements["comparison"] = (f"Den korte søgning foretrækker {stronger['san']} frem for {weaker['san']}. Sammenlign de lovlige svar; rangeringen forklarer ikke alene den strategiske årsag." if da else
                f"The short search ranks {stronger['san']} above {weaker['san']}. Compare their legal replies; that ranking alone does not prove a strategic explanation.")
    if not learner_turn:
        for key in ("comparison", "line_0", "line_1", "line_2", "line_3", "line_4"):
            if key in statements: statements[key] = f"For {root_name}: " + statements[key]
    if review_requested(context):
        # Use only stored pre-move assessments supplied for the selected position.
        labels = {"Best": "bedste træk", "Excellent": "fremragende", "Good": "godt træk",
                  "Inaccuracy": "unøjagtighed", "Mistake": "fejl", "Blunder": "alvorlig fejl",
                  "Forced": "tvunget træk", "Uncertain": "usikker vurdering"}
        counts = {label: context.get("game", {}).get("assessment_counts", {}).get(label, 0) for label in labels}
        assessed = sum(counts.values())
        if assessed:
            grades = ", ".join(f"{count} {labels[label] if da else label}" for label, count in counts.items() if count)
            statements["review"] = (f"Gennemgået {assessed} af dine træk frem til denne stilling: {grades}. Vurderingerne er estimater fra korte søgninger." if da else
                f"Reviewed {assessed} of your moves up to this position: {grades}. These grades are short-search estimates.")
        else:
            statements["review"] = ("Der er endnu ingen vurderede træk at gennemgå i denne stilling. Spil et træk i et træningsparti for at få en vurdering." if da else
                "There are no assessed moves to review at this position yet. Play a move in a training game to get an assessment.")
    decision = context.get("game", {}).get("last_player_decision")
    if decision and decision.get("feedback", {}).get("fen") == decision.get("before_fen"):
        feedback = decision["feedback"]
        # Recompute the explanation from its original board, never attribute it to the current FEN.
        original = chess.Board(decision["before_fen"])
        move = parse_move(original, decision["uci"])
        names = {"Best": "bedste træk", "Excellent": "fremragende", "Good": "godt træk", "Inaccuracy": "unøjagtighed", "Mistake": "fejl", "Blunder": "alvorlig fejl", "Forced": "tvunget træk", "Uncertain": "usikker vurdering"}
        label = names.get(feedback.get("classification"), "usikker vurdering") if da else feedback.get("classification", "Uncertain")
        statements["previous_assessment"] = (f"Din tidligere beslutning {decision['san']} blev vurderet som {label} ud fra stillingen før trækket, ikke ud fra modstanderens senere svar." if da else
            f"Your earlier decision {decision['san']} was assessed as {label} from its original position, using its pre-move search rather than the opponent's later reply.")
        statements["previous_reason"] = move_idea(move_facts(original, move), language)
        after = original.copy()
        after.push(move)
        own_previous = "white" if original.turn else "black"
        exposed = [p for p in observations(after)["exposed_pieces"] if p["color"] == own_previous]
        if exposed:
            squares = ", ".join(p["square"] for p in exposed[:2])
            statements["previous_consequence"] = (f"Umiddelbart efter {decision['san']} var dine brikker på {squares} angrebet og udækkede. En gevinst skal stadig verificeres i en variant." if da else
                f"Immediately after {decision['san']}, your pieces on {squares} were attacked and undefended. Whether a capture wins still needs variation analysis.")
        elif feedback.get("played", {}).get("mate") is not None and feedback["played"]["mate"] < 0:
            statements["previous_consequence"] = "Søgningen efter dit valgte træk fandt en tvungen mat mod dig." if da else "The search of your chosen move found a forced mate against you."
        elif feedback.get("classification") in ("Mistake", "Blunder", "Inaccuracy"):
            statements["previous_consequence"] = "Søgningen foretrak et alternativ; den præcise årsag er ikke selvstændigt verificeret." if da else "The search preferred an alternative; the exact reason has not been independently verified."
    if not context["analysis"].get("candidates") and not board.is_game_over(claim_draw=True):
        statements["offline"] = "Skakmotoren er utilgængelig; rådene bygger kun på lovlige træk og brættets geometri." if da else "The engine is unavailable; this advice uses legal moves and board geometry only."
    return statements


def fallback_keys(context: dict, statements: dict, reveal: bool) -> list[str]:
    question = context["question"].lower()
    keys = [key for key in ("terminal", "turn", "check", "offline") if key in statements]
    if review_requested(context) and "review" in statements:
        keys.insert(0, "review")
    if review_requested(context) or any(word in question for word in ("last", "bad", "mistake", "why was", "blunder", "previous", "sidste", "fejl", "hvorfor var")):
        keys += [key for key in ("previous_assessment", "previous_reason", "previous_consequence") if key in statements]
    if any(word in question for word in ("castle", "rokad", "king safety", "kongens sikker")): keys.append("castle")
    if "unavailable_piece" in statements: keys.append("unavailable_piece")
    if reveal:
        keys += [key for key in ("candidate_0", "candidate_1", "comparison", "line_0", "consequence_0") if key in statements]
    if any(word in question for word in ("vulnerab", "undefended", "threat", "defend", "angreb", "udækket", "trus", "forsvar")):
        keys += [key for key in statements if key.startswith("exposed_")][:2]
        keys += [key for key in ("defended_attack", "no_exposed") if key in statements]
    if "center" in question or "centrum" in question:
        if "center" in statements: keys.append("center")
    if "recognition" in statements: keys += ["recognition", "attackers_0"]
    if any(word in question for word in ("which piece", "which opponent", "hvilken brik", "angriber")):
        keys += [key for key in statements if key.startswith("attackers_")][:2]
    if len(keys) < 2:
        exposed = next((key for key in statements if key.startswith("exposed_")), None)
        if exposed: keys.append(exposed)
        keys.append("plan")
    if context["preferences"].get("coaching_mode") == "socratic" and context["preferences"].get("guided_questions", True):
        keys.append("question")
    else: keys.append("habit")
    return list(dict.fromkeys(keys))
