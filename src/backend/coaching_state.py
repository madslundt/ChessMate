"""A small discovery dialogue whose progress is backed by the exact board and engine line."""
import hashlib
import re

import chess

from .chess_tools import observations, parse_move, variation_evidence
from .coach_facts import PIECES_DA, side_name


def state_key(user_id: str, game_id: str | None, fen: str) -> str:
    return hashlib.sha256(repr((user_id, game_id, fen)).encode()).hexdigest()


def public_state(state: dict) -> dict:
    return {key: state[key] for key in ("stage", "discovered_ids", "mode", "turns", "question", "acknowledgement", "help_level") if key in state}


def outcome_claim(question: str, state: dict, language: str) -> tuple[bool, str]:
    """Check simple learner conclusions against the replayed line, without claiming all replies are forced."""
    outcome = state.get("line_outcome", {})
    if not outcome: return False, ""
    da = language == "da"
    learner = state.get("learner_color", outcome.get("perspective"))
    delta = outcome.get("material_change", 0) * (1 if learner == outcome.get("perspective") else -1)
    terminal, winner = outcome.get("terminal"), outcome.get("winner")
    losing_mate = terminal == "checkmate" and winner != learner
    winning_mate = terminal == "checkmate" and winner == learner
    declared_win = bool(re.search(r"\b(?:i win|i'm winning|i am winning|jeg vinder)\b(?!\s+(?:a\b|the\b|material|\d|queen|rook|pawn))", question))
    declared_loss = bool(re.search(r"\b(?:i get checkmated|i am checkmated|i'm checkmated|i lose|jeg bliver mat|jeg taber)\b(?!\s+(?:a\b|the\b|material|\d|queen|rook|pawn))", question))
    declared_draw = any(term in question for term in ("it is a draw", "it's a draw", "stalemate", "det er remis", "det er pat"))
    material = re.search(r"(material(?: balance| change)?|materialebalance)\s*(?:changes by|change|is|er|of|på|:)?\s*([+-]?\d+)\b", question)
    if declared_win:
        correct = winning_mate
        text = ("Ja, denne variant ender med mat til dig; det er stadig netop denne variant." if correct else
                "Denne variant beviser ikke en gevinst til dig. " + ("Den ender faktisk med skakmat mod dig." if losing_mate else "Undersøg slutstillingen og undgå at forveksle et motor-estimat med et bevist resultat.")) if da else (
                "Yes, this continuation ends in checkmate for your side; that is the result of this particular line." if correct else
                "This continuation does not prove a win for your side. " + ("It actually ends in checkmate against you." if losing_mate else "Inspect the final position and distinguish a search estimate from a proven result."))
        return correct, text
    if declared_loss:
        correct = losing_mate
        return correct, (("Ja: slutstillingen i denne variant er skakmat mod dig." if correct else "Slutstillingen bekræfter ikke skakmat mod dig; undersøg kongerne igen.") if da else
                         ("Yes: the final position of this continuation is checkmate against your side." if correct else "The final position does not confirm checkmate against your side; check the kings again."))
    if declared_draw:
        correct = terminal is not None and winner is None
        return correct, (("Ja, netop denne variant ender remis." if correct else "Denne variants slutstilling er ikke en afsluttet remis; undersøg pat og materialet igen.") if da else
                         ("Yes, this particular continuation ends in a draw." if correct else "This continuation does not end in a terminal draw; check stalemate and material again."))
    captured_claim = re.search(r"\bi (?:win|gain|take|capture) (?:a |the )?(queen|rook|bishop|knight|pawn)\b", question)
    if captured_claim:
        piece_type = {"queen": chess.QUEEN, "rook": chess.ROOK, "bishop": chess.BISHOP, "knight": chess.KNIGHT, "pawn": chess.PAWN}[captured_claim.group(1)]
        captured = False
        for frame in outcome.get("frames", []):
            position = chess.Board(frame["before_fen"])
            move = chess.Move.from_uci(frame["uci"])
            if ("white" if position.turn else "black") != learner: continue
            victim = position.piece_type_at(move.to_square)
            if victim == piece_type or piece_type == chess.PAWN and position.is_en_passant(move): captured = True
        correct = captured and not losing_mate
        if losing_mate:
            return False, ("Der bliver slået materiale i varianten, men din side bliver skakmat. En materiel gevinst afgør ikke dette resultat." if da else
                           "Material is captured in the continuation, but your side is checkmated. A material gain does not decide this result.")
        return correct, (("Ja, den brik bliver slået i netop denne variant; andre svar kan ændre resultatet." if correct else "Din side slår ikke den brik i den viste variant. Spil varianten frem og tæl slagene igen.") if da else
                         ("Yes, that piece is captured by your side in this particular continuation; other replies may change the result." if correct else "Your side does not capture that piece in the shown continuation. Step through it and count the captures again."))
    if material:
        claimed = int(material.group(2))
        change_claim = "change" in material.group(0) or "ændr" in material.group(0)
        final = chess.Board(outcome["resulting_fen"])
        values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
        balance = sum(values[piece.piece_type] * (1 if piece.color == (learner == "white") else -1) for piece in final.piece_map().values())
        actual = delta if change_claim else balance
        correct = claimed == actual and not losing_mate
        sentence = (f"Materialebalancen ændres med {delta:+}" if change_claim else f"Din materialebalance er {balance:+}") if da else (
                   f"The material balance changes by {delta:+}" if change_claim else f"Your material balance is {balance:+}")
        return correct, sentence + ((" i netop denne variant. " + ("Men du bliver skakmat, så materialet afgør ikke resultatet." if losing_mate else "Andre svar kan ændre dette resultat.")) if da else
                         (" in this specific continuation. " + ("But your side is checkmated, so material does not decide the result." if losing_mate else "Other replies may change this result.")))
    return False, ""


def advance_discovery(board: chess.Board, context: dict, previous: dict | None, mode: str | None = None, language: str = "en") -> dict:
    state = {"stage": "notice", "discovered_ids": [], "mode": "guided" if context["preferences"].get("coaching_mode") == "socratic" else "direct",
             "turns": 0, **(previous or {})}
    question = context["question"].lower()
    if mode is not None: state["mode"] = mode
    elif any(term in question for term in ("just tell me", "direct explanation", "explain directly", "forklar direkte")): state["mode"] = "direct"
    elif any(term in question for term in ("guide me", "ask me", "socratic", "hjælp mig selv", "stil spørgsmål")): state["mode"] = "guided"
    state["turns"] += 1
    state["learner_color"] = context["learner_color"]
    outcome = board.outcome(claim_draw=True)
    if outcome is not None:
        reason = outcome.termination.name.lower().replace("_", " ")
        reason_da = {"checkmate": "skakmat", "stalemate": "pat", "insufficient material": "utilstrækkeligt materiale",
            "threefold repetition": "tredobbelt stillingsgentagelse", "fivefold repetition": "femdobbelt stillingsgentagelse",
            "fifty moves": "halvtredstræksreglen", "seventyfive moves": "femoghalvfjerdstræksreglen"}.get(reason, reason)
        state.update(stage="reflect", help_level=0,
            acknowledgement=f"Stillingen er afsluttet efter {reason_da}." if language == "da" else f"This position has ended by {reason}.",
            question="Hvilken læring vil du tage med fra denne afsluttede stilling?" if language == "da" else
                     "What lesson will you take from this finished position?")
        for key in ("candidate_uci", "expected_reply_uci", "line_outcome"): state.pop(key, None)
        return state
    discovered = list(state.get("discovered_ids", []))
    da = language == "da"
    acknowledgement = ""
    own = context["learner_color"]
    facts = context["analysis"].get("observations") or observations(board)
    exposed = [item for item in facts["exposed_pieces"] if item["color"] == own]
    squares = set(re.findall(r"\b[a-h][1-8]\b", question))
    for item in exposed:
        identifier = "exposed:" + item["square"]
        if item["square"] in squares and identifier not in discovered:
            discovered.append(identifier)
            state["focus_square"] = item["square"]
            state["stage"] = "identify"
            acknowledgement = (f"Ja: brikken på {item['square']} er angrebet og geometrisk udækket. Det er ikke alene bevis for en vundet brik." if da else
                f"Yes: the piece on {item['square']} is attacked and geometrically undefended. That alone does not prove a winning capture.")
        if identifier in discovered:
            for attacker in item["attackers"]:
                attacker_id = f"attacker:{item['square']}:{attacker}"
                if attacker in squares and attacker_id not in discovered:
                    discovered.append(attacker_id)
                    state["stage"] = "calculate"
                    acknowledgement = (f"Rigtigt: brikken på {attacker} angriber geometrisk {item['square']}. Nu skal det lovlige svar undersøges." if da else
                        f"Correct: the piece on {attacker} geometrically attacks {item['square']}. Now test the legal reply.")
    # Once a candidate is chosen, interpret later reply notation on its hypothetical board.
    candidate_value = state.get("candidate_uci")
    reply_attempt = False
    if candidate_value and state.get("expected_reply_uci"):
        variation = board.copy()
        try:
            variation.push(parse_move(variation, candidate_value))
            for token in context["question"].split():
                try: reply = parse_move(variation, token.strip(".,!?;:()[]\"'"))
                except ValueError: continue
                reply_attempt = True
                if reply.uci() == state["expected_reply_uci"]:
                    discovered.append("reply:" + reply.uci())
                    state["stage"] = "evaluate"
                    acknowledgement = (f"Ja: {variation.san(reply)} er svaret i den aktuelle motorvariant. Det er et søgningsestimat, ikke det eneste mulige svar." if da else
                        f"Yes: {variation.san(reply)} is the reply in the current engine continuation. This is a search estimate, not the only possible reply.")
                else:
                    acknowledgement = ("Dit foreslåede svar er lovligt i varianten, men det er ikke svaret i den aktuelle motorvariant. Undersøg tvingende svar igen." if da else
                        "Your proposed reply is legal in the variation, but differs from the current engine continuation. Check forcing replies again.")
                break
        except ValueError:
            state.pop("candidate_uci", None)
            state.pop("expected_reply_uci", None)
    if reply_attempt: context["requested_candidates"] = []
    if not reply_attempt and state["stage"] != "evaluate" and context.get("requested_candidates"):
        candidate = context["requested_candidates"][0]
        discovered.append("candidate:" + candidate["uci"])
        state["candidate_uci"] = candidate["uci"]
        line = candidate.get("pv_uci", [])
        if len(line) > 1: state["expected_reply_uci"] = line[1]
        if line: state["line_outcome"] = variation_evidence(board, line)
        state["stage"] = "calculate"
    if state["stage"] == "evaluate":
        correct, evaluation = outcome_claim(question, state, language)
        if evaluation: acknowledgement = evaluation
        if correct:
            discovered.append("evaluated:" + state.get("candidate_uci", "line"))
            state["stage"] = "reflect"
    focus = state.get("focus_square")
    prompts = {
        "notice": ("Hvilken af dine brikker er angrebet og uden geometrisk forsvarer? Vælg dens felt." if exposed else "Hvilke lovlige skakker og slag bør du undersøge først?") if da else
                  ("Which of your pieces is attacked and has no geometric defender? Select its square." if exposed else "Which legal checks and captures would you examine first?"),
        "identify": (f"Hvilken modstanderbrik angriber {focus}? Angiv dens felt." if da else f"Which enemy piece attacks {focus}? Name its square."),
        "calculate": "Vælg et kandidatetræk, og forudsig derefter modstanderens tvingende svar i varianten." if da else "Choose a candidate move, then predict the opponent's forcing reply in the variation.",
        "evaluate": "Spil varianten frem. Hvad ændrer sig i materialet eller kongens sikkerhed?" if da else "Step through the continuation. What changes in material or king safety?",
        "reflect": "Hvilken kontrol vil du bruge før dit næste træk for at anvende denne idé igen?" if da else "What will you check before your next move to apply this idea again?",
    }
    state["question"] = prompts[state["stage"]]
    help_request = any(term in question for term in ("don't know", "do not know", "hint", "help", "can't see", "ved ikke", "hjælp"))
    attempts = dict(state.get("help_attempts", {}))
    if help_request:
        attempts[state["stage"]] = min(3, attempts.get(state["stage"], 0) + 1)
        level = attempts[state["stage"]]
        if state["stage"] == "notice" and exposed:
            target = exposed[0]
            state["question"] = ((f"Se efter en {PIECES_DA[target['piece']]} uden forsvarer." if level == 1 else f"Undersøg brikken på {target['square']}. Hvem angriber den?") if da else
                (f"Look for a {target['piece']} without a defender." if level == 1 else f"Inspect the piece on {target['square']}. Who attacks it?"))
        elif state["stage"] == "identify" and focus:
            item = next((piece for piece in exposed if piece["square"] == focus), None)
            if item and item["attackers"]:
                attacker = item["attackers"][0]
                state["question"] = (("Følg angrebslinjerne fra feltet og undersøg springerangreb." if level == 1 else f"Undersøg modstanderbrikken på {attacker}; kan den lovligt slå {focus}?") if da else
                    ("Trace the attack lines from the square and check knight attacks." if level == 1 else f"Inspect the enemy piece on {attacker}; can it legally capture on {focus}?"))
        elif state["stage"] == "calculate" and level >= 2 and context["analysis"].get("candidates"):
            facts = context["analysis"]["candidates"][0].get("facts", {})
            if facts.get("from"):
                state["question"] = (f"Undersøg brikken på {facts['from']}, men vælg selv dens destination og forudsig svaret." if da else
                    f"Focus on the piece on {facts['from']}, then choose its destination yourself and predict the reply.")
        elif state["stage"] == "evaluate" and level >= 2:
            outcome = state.get("line_outcome", {})
            if outcome.get("terminal") == "checkmate":
                winner = outcome.get("winner")
                winning_side = side_name(winner == "white", da)
                state["question"] = (f"Netop denne variant ender med skakmat, og {winning_side} vinder. Hvad betyder det for materialet?" if da else
                    f"This particular continuation ends in checkmate, and {winning_side} wins. What does that mean for the material count?")
    state["help_attempts"] = attempts
    state["help_level"] = attempts.get(state["stage"], 0)
    state["acknowledgement"] = acknowledgement
    state["discovered_ids"] = list(dict.fromkeys(discovered))[-40:]
    return state
