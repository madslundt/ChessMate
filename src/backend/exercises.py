"""Verified curriculum content and deterministic learning-objective predicates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chess

CATEGORIES = ("forks", "pins", "skewers", "opening", "middlegame", "endgame")
LIBRARY_PATH = Path(__file__).with_name("exercise_library.json")
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def read_library(path: Path = LIBRARY_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def parse_move(board: chess.Board, text: str) -> chess.Move:
    try:
        move = chess.Move.from_uci(text.strip())
        if move not in board.legal_moves:
            raise ValueError("Illegal move")
        return move
    except ValueError:
        try:
            return board.parse_san(text.strip())
        except ValueError as exc:
            raise ValueError("Choose a legal move in the exercise position.") from exc


def _skewers(board: chess.Board, square: int) -> bool:
    piece = board.piece_at(square)
    if piece is None or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return False
    directions = []
    if piece.piece_type in (chess.ROOK, chess.QUEEN):
        directions += [(0, 1), (0, -1), (1, 0), (-1, 0)]
    if piece.piece_type in (chess.BISHOP, chess.QUEEN):
        directions += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    for dx, dy in directions:
        x, y = chess.square_file(square) + dx, chess.square_rank(square) + dy
        occupied = []
        while 0 <= x < 8 and 0 <= y < 8:
            target = board.piece_at(chess.square(x, y))
            if target:
                occupied.append(target)
                if len(occupied) == 2:
                    break
            x, y = x + dx, y + dy
        if len(occupied) == 2 and all(p.color != piece.color for p in occupied):
            if occupied[0].piece_type == chess.KING and occupied[1].piece_type in (chess.ROOK, chess.QUEEN):
                return True
    return False


def relative_pins(board: chess.Board, color: bool) -> set[tuple[int, int]]:
    """Geometric relative pins: an attacked piece shields a more valuable non-king."""
    found = set()
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for front in board.attacks(square):
            target = board.piece_at(front)
            if not target or target.color == color or target.piece_type == chess.KING:
                continue
            dx, dy = chess.square_file(front) - chess.square_file(square), chess.square_rank(front) - chess.square_rank(square)
            dx, dy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
            x, y = chess.square_file(front) + dx, chess.square_rank(front) + dy
            while 0 <= x < 8 and 0 <= y < 8:
                back = chess.square(x, y)
                shielded = board.piece_at(back)
                if shielded:
                    if shielded.color != color and shielded.piece_type != chess.KING and VALUES[shielded.piece_type] > VALUES[target.piece_type]:
                        found.add((front, back))
                    break
                x, y = x + dx, y + dy
    return found


def objective_met(board: chess.Board, move: chess.Move, criterion: dict[str, Any]) -> bool:
    """Geometry is necessary; a separate engine comparison verifies tactical soundness."""
    if move not in board.legal_moves:
        return False
    after = board.copy(stack=False)
    color = board.turn
    after.push(move)
    kind = criterion["kind"]
    if kind == "relative_pin":
        return bool(relative_pins(after, color) - relative_pins(board, color))
    if kind == "exploit_pin":
        pinned = [sq for sq in board.piece_map() if board.color_at(sq) == (not color) and board.is_pinned(not color, sq)]
        return board.is_capture(move) and any(move.to_square in board.attacks(sq) and
            not any(reply.from_square == sq and reply.to_square == move.to_square for reply in after.legal_moves) for sq in pinned)
    if kind == "unpin":
        pinned = [sq for sq in board.piece_map() if board.color_at(sq) == color and board.is_pinned(color, sq)]
        return any(after.piece_at(sq) == board.piece_at(sq) and not after.is_pinned(color, sq) for sq in pinned)
    if kind == "defend":
        target = chess.parse_square(criterion["target"])
        return (board.color_at(target) == color and board.is_attacked_by(not color, target)
                and not board.is_attacked_by(color, target) and after.piece_at(target) == board.piece_at(target)
                and after.is_attacked_by(color, target))
    if kind == "outpost":
        rank = chess.square_rank(move.to_square)
        return (board.piece_type_at(move.from_square) == chess.KNIGHT and (rank >= 3 if color else rank <= 4)
                and any(after.piece_type_at(sq) == chess.PAWN for sq in after.attackers(color, move.to_square))
                and not any(after.piece_type_at(sq) == chess.PAWN for sq in after.attackers(not color, move.to_square)))
    if kind == "simplify":
        piece, victim = board.piece_at(move.from_square), board.piece_at(move.to_square)
        advantage = sum(VALUES[p.piece_type] * (1 if p.color == color else -1) for p in board.piece_map().values())
        return bool(piece and victim and piece.piece_type == victim.piece_type == chess.QUEEN and advantage >= 3
                    and any(reply.to_square == move.to_square and after.is_capture(reply) for reply in after.legal_moves))
    if kind == "repair_pawns":
        def doubled(position: chess.Board) -> int:
            return sum(max(0, len([sq for sq in position.pieces(chess.PAWN, color) if chess.square_file(sq) == file]) - 1) for file in range(8))
        return board.piece_type_at(move.from_square) == chess.PAWN and board.is_capture(move) and doubled(after) < doubled(board)
    if kind == "opposition":
        own, enemy = after.king(color), after.king(not color)
        dx, dy = abs(chess.square_file(own) - chess.square_file(enemy)), abs(chess.square_rank(own) - chess.square_rank(enemy))
        return board.piece_type_at(move.from_square) == chess.KING and (dx, dy) in ((0, 2), (2, 0))
    if kind == "hold_corner":
        return board.piece_type_at(move.from_square) == chess.KING and move.to_square == chess.parse_square(criterion["corner"])
    if kind == "rook_seventh":
        return board.piece_type_at(move.from_square) == chess.ROOK and chess.square_rank(move.to_square) == (6 if color else 1)
    if kind in ("fresh_development", "finish_development"):
        developed = objective_met(board, move, {"kind": "develop"})
        if kind == "finish_development":
            return developed and any(chess.square_rank(sq) != (0 if color else 7) for sq in board.pieces(chess.QUEEN, color))
        previous = chess.parse_square(criterion["previous_square"])
        return (developed and board.color_at(previous) == color
                and board.piece_type_at(previous) in (chess.KNIGHT, chess.BISHOP)
                and chess.square_rank(previous) != (0 if color else 7) and move.from_square != previous)
    if kind == "fork":
        targets = [s for s in after.attacks(move.to_square)
                   if after.piece_at(s) and after.color_at(s) != color
                   and VALUES[after.piece_type_at(s)] >= 3]
        return len(targets) >= 2 and not after.is_attacked_by(not color, move.to_square)
    if kind == "pin":
        return any(after.is_pinned(not color, s) and not board.is_pinned(not color, s)
                   for s in after.piece_map() if after.color_at(s) != color and after.piece_type_at(s) != chess.KING)
    if kind == "skewer":
        return _skewers(after, move.to_square)
    if kind == "develop":
        piece = board.piece_at(move.from_square)
        return bool(piece and piece.piece_type in (chess.BISHOP, chess.KNIGHT)
                    and chess.square_rank(move.from_square) == (0 if color else 7)
                    and chess.square_rank(move.to_square) != (0 if color else 7))
    if kind == "castle":
        return board.is_castling(move)
    if kind == "pawn_challenge":
        return board.piece_type_at(move.from_square) == chess.PAWN and any(
            square in (chess.D4, chess.E4, chess.D5, chess.E5)
            and after.piece_type_at(square) == chess.PAWN and after.color_at(square) != color
            for square in after.attacks(move.to_square))
    if kind == "center":
        return board.piece_type_at(move.from_square) == chess.PAWN and move.to_square in [chess.D4, chess.E4, chess.D5, chess.E5]
    if kind == "capture":
        captured = board.piece_at(move.to_square)
        attacker = board.piece_at(move.from_square)
        return bool(captured and attacker and VALUES[captured.piece_type] >= criterion.get("min_value", 1))
    if kind == "mate":
        return after.is_checkmate()
    if kind == "promote":
        return bool(move.promotion) and not after.is_stalemate()
    if kind == "king_activity":
        return board.piece_type_at(move.from_square) == chess.KING
    if kind == "engine":
        return True
    return False


def validate_structure(item: dict[str, Any]) -> chess.Board:
    required = {"id", "title", "category", "difficulty", "fen", "objective", "solution", "criterion", "explanation", "hints", "tags"}
    if required - item.keys():
        raise ValueError(f"Missing exercise fields: {sorted(required - item.keys())}")
    if item["category"] not in CATEGORIES:
        raise ValueError("Unknown category")
    if not isinstance(item["difficulty"], int) or not 1 <= item["difficulty"] <= 5:
        raise ValueError("Difficulty must be 1–5")
    board = chess.Board(item["fen"])
    if not board.is_valid() or board.is_game_over():
        raise ValueError(f"Invalid or terminal exercise: {item['id']}")
    if not 1 <= len(item["solution"]) <= 16 or not 1 <= len(item["hints"]) <= 4:
        raise ValueError("A solution and progressive hints are required")
    move = parse_move(board, item["solution"][0])
    if not objective_met(board, move, item["criterion"]):
        raise ValueError(f"Solution does not achieve its objective: {item['id']}")
    for text in item["solution"]:
        board.push(parse_move(board, text))
    return chess.Board(item["fen"])


def public_exercise(item: dict[str, Any]) -> dict[str, Any]:
    public = {key: item[key] for key in ("id", "title", "category", "difficulty", "fen", "objective", "tags")}
    public["description"] = item.get("description", _CONCEPT_INTROS["en"][item["category"]])
    return public


_DANISH = {
    "fork": ("Skab en gaffel mod to værdifulde brikker.", "En gaffel angriber to mål på én gang. Undersøg begge trusler og modstanderens bedste svar."),
    "pin": ("Skab en absolut binding foran modstanderens konge.", "En brik er bundet til kongen, når den ikke kan flyttes uden at efterlade kongen i skak. Udnyt begrænsningen, men kontrollér stadig modstanderens svar."),
    "skewer": ("Skab en spidning gennem kongen mod en værdifuld brik.", "Din langtrækkende brik giver skak med en værdifuld brik bag kongen. Når kongen flytter væk fra linjen, bliver brikken bagved angrebet."),
    "develop": ("Udvikl en let officer fra dens udgangsfelt.", "Udvikling bringer dine springere og løbere i spil. Trækket følger princippet og er kontrolleret med skakmotoren."),
    "castle": ("Rokér for at bringe kongen i sikkerhed.", "Rokade flytter kongen væk fra centrum og bringer tårnet i spil. Kontrollér altid, at kongens nye stilling er sikker."),
    "center": ("Ryk en centrumsbonde frem og kæmp om centrum.", "Centrumsbønder kontrollerer vigtige felter og giver officererne plads. Sammenlign altid princippet med den konkrete stilling."),
    "capture": ("Find en sund erobring af en værdifuld brik.", "Undersøg alle slag, før du vælger en plan. Her giver det kontrollerede slag en konkret fordel; husk også at undersøge modstanderens svar."),
    "mate": ("Sæt modstanderens konge skakmat i ét træk.", "Tag kongens flugtfelter væk og giv derefter skak. Kongen kan hverken flygte, slå den angribende brik eller blokere skakken."),
    "promote": ("Forvandl fribonden uden at sætte modstanderen pat.", "En bonde på sidste række kan blive en dronning. Her har modstanderen stadig lovlige træk efter forvandlingen, så stillingen er ikke pat."),
    "king_activity": ("Aktivér kongen uden at forringe stillingens resultat.", "I bondeslutspil er kongen en aktiv brik. Gå mod vigtige felter, mens du passer på bønderne og modstanderens konge."),
    "pawn_challenge": ("Udfordr modstanderens centrum med et bondetræk.", "Bonden angriber modstanderens centrumsbonde. Undersøg svarene, før du vurderer, om en bonde kan vindes."),
    "engine": ("Find et sundt træk, der følger stillingens plan.", "Sammenlign centrumsindflydelse, udvikling og kongesikkerhed. Motoranalysen bekræfter, at trækket er et sundt valg."),
}
_DANISH.update({
    "relative_pin": ("Skab en relativ binding af en springer foran dronningen.", "Løberen angriber springeren med dronningen bagved. Springeren må lovligt flytte, men åbner dermed linjen mod den mere værdifulde dronning."),
    "exploit_pin": ("Slå bonden, som en absolut bundet springer tilsyneladende forsvarer.", "Springeren angriber bondens felt, men er bundet til kongen af en langtrækkende brik. Et genslag med springeren ville åbne en skak mod kongen og er derfor ulovligt."),
    "unpin": ("Ophæv den absolutte binding uden at flytte springeren.", "Bondetrækket blokerer løberens diagonal til kongen og angriber samtidig løberen. Springeren er ikke længere absolut bundet."),
    "defend": ("Tilføj en forsvarer til den angrebne, uforsvarede springer på d4 uden at flytte den.", "Løberen angriber springeren på d4. Tårnet forsvarer den langs en åben linje og får samtidig en aktiv rolle. Motoren kontrollerer, at forsvaret holder."),
    "outpost": ("Flyt springeren til et fremskudt, bondestøttet felt, som ingen fjendtlig bonde angriber nu.", "Springeren forlader kanten og får et fremskudt felt med bondestøtte. Ingen fjendtlig bonde angriber feltet nu. Kontrollér stadig, om modstanderens officerer kan udfordre den."),
    "simplify": ("Slå modstanderens dronning og beregn tårnets mulige genslag.", "Du har en let officer i overskud. Dronningeslaget tillader et genslag med tårnet, så dronningerne kan byttes uden at miste materialeovervægten. Kontrollér altid genslaget først."),
    "repair_pawns": ("Slå med en dobbeltbonde, så antallet af dobbeltbønder falder.", "c-bonden slår ind mod centrum. De to bønder står derefter på forskellige linjer, så antallet af dobbeltbønder falder. Slaget vinder også den tilgængelige bonde, og motoren kontrollerer taktikken."),
    "opposition": ("Tag direkte opposition: stil kongerne over for hinanden med ét tomt felt imellem og modstanderen i trækket.", "Kongerne står over for hinanden med ét tomt felt imellem, og modstanderen skal trække. Oppositionen kan hjælpe din konge frem; motoranalysen bekræfter, at trækket bevarer stillingens bedste resultat."),
    "hold_corner": ("Nå tårnbondens forvandlingshjørne med den forsvarende konge.", "Kongen når a8 foran tårnbonden. Angriberen kan ikke tvinge den ud af hjørnet, og motoren vurderer stillingen til remis. Hjørnet er en vigtig forsvarsressource."),
    "rook_seventh": ("Før tårnet til syvende række, hvor det kan angribe modstanderens bønder fra siden.", "Tårnet når syvende række og slår a-bonden. Det angriber også bondelinjen langs rækken. Kontrollér stadig modstanderens tårnskakker og modspil."),
    "finish_development": ("Udvikl en let officer i stedet for at flytte dronningen igen.", "Dronningen har allerede forladt udgangsfeltet. Ved at udvikle en ny let officer får du endnu en brik i spil uden at bruge et nyt tempo på dronningen. Motoren bekræfter, at trækket er spilbart."),
    "fresh_development": ("Udvikl en ny let officer i stedet for at flytte springeren på c3 igen.", "En ny let officer kommer i spil, mens springeren på c3 beholder sin plads i centrum. Udvikl normalt flere brikker, før du gentager træk uden en konkret grund; her understøttes valget af motoranalysen."),
})
_CONCEPT_INTROS = {
    "en": {
        "forks": "A fork attacks two targets at once. Knights, pawns, and queens can all create forks. Check the opponent’s strongest reply before assuming either target is won.",
        "pins": "An absolute pin ties a piece to its king, so moving off the line is illegal. A relative pin ties a piece to more valuable material: it may move legally, but doing so can be costly. Look for ways to create, exploit, and break pins.",
        "skewers": "A skewer puts the more valuable piece in front of a second target on the same line. When the front piece moves away, the piece behind it is exposed. In a pin, the less valuable piece is in front.",
        "opening": "Opening principles help you contest the center, develop your minor pieces, and keep your king safe. Avoid repeated piece moves or early queen adventures unless a concrete threat justifies them.",
        "middlegame": "Start by finding the opponent’s threats and your undefended pieces. Then compare active piece placement, useful exchanges, pawn structure, and short forcing variations before selecting a plan.",
        "endgame": "In an endgame, active kings and rooks, passed pawns, and exact calculation matter. Learn which positions win and which draw; promotion and stalemate can change the result immediately.",
    },
    "da": {
        "forks": "En gaffel angriber to mål på én gang. Springere, bønder og dronninger kan alle lave gafler. Undersøg modstanderens bedste svar, før du regner et mål som vundet.",
        "pins": "En absolut binding binder en brik til kongen, så den ikke lovligt kan åbne linjen. En relativ binding binder brikken til mere værdifuldt materiale: den må flytte, men det kan koste dyrt. Lær at skabe, udnytte og ophæve bindinger.",
        "skewers": "I en spidning står den mere værdifulde brik foran et andet mål på samme linje. Når den forreste brik flytter, bliver brikken bagved udsat. I en binding står den mindre værdifulde brik forrest.",
        "opening": "Åbningsprincipper hjælper dig med at kæmpe om centrum, udvikle lette officerer og beskytte kongen. Undgå gentagne briktræk og tidlige dronningture uden en konkret grund.",
        "middlegame": "Find først modstanderens trusler og dine uforsvarede brikker. Sammenlign derefter aktivitet, afbytninger, bondestruktur og korte forcerede varianter, før du vælger en plan.",
        "endgame": "Aktive konger og tårne, fribønder og præcis beregning er vigtige i slutspillet. Lær, hvilke stillinger der vinder eller holder remis; forvandling og pat kan straks ændre resultatet.",
    },
}
_INTRO_DA = {
    "relative_pin": "En relativ binding binder en brik til en mere værdifuld brik. Den bundne brik må lovligt flytte, men du skal beregne, om det kan betale sig at åbne linjen bag den.",
    "exploit_pin": "En absolut bundet brik kan se ud til at forsvare et felt uden lovligt at kunne slå tilbage. Kontrollér linjen til kongen, før du tæller den som forsvarer.",
    "unpin": "En binding kan brydes ved at flytte brikken bagved, blokere linjen, slå angriberen eller tvinge den væk. Kontrollér, at den bundne brik bliver bevaret.",
    "defend": "Find angrebne og uforsvarede brikker, før du angriber. Et forsvarstræk kan samtidig forbedre en anden briks placering. Tæl angribere og forsvarere igen efter trækket.",
    "outpost": "En nyttig springerforpost har bondestøtte og bliver ikke straks jaget af en fjendtlig bonde. Feltet er ikke permanent sikkert: vurder også modstanderens officerer.",
    "simplify": "Når du har materialeovervægt, kan en sund afbytning af tunge officerer mindske modstanderens angrebsmuligheder. Beregn genslaget og vurder den resterende stilling.",
    "repair_pawns": "Dobbeltbønder deler en linje og kan være sværere at forsvare. Et sundt slag til nabolinjen kan reparere strukturen, men kontrollér først taktikken.",
    "opposition": "Direkte opposition betyder, at kongerne står over for hinanden med ét felt imellem. Spilleren uden træktvang kan ofte kontrollere det næste vigtige kongefelt; værdien afhænger af bønderne.",
    "hold_corner": "En tårnbonde på a- eller h-linjen har færre veje uden om en forsvarende konge. Når forsvareren når forvandlingshjørnet i tide, kan mange af disse slutspil holdes remis.",
    "rook_seventh": "På syvende række kan et aktivt tårn angribe modstanderens bønder fra siden. Afvej aktiviteten mod skakker, kongesikkerhed og modstanderens tårntrusler.",
    "finish_development": "Tidlige dronningtræk kan koste tid, hvis modstanderen udvikler med angreb på dronningen. Når den ikke er truet nu, bør du sammenligne udvikling af lette officerer med endnu en dronningtur.",
    "fresh_development": "Gentagne træk med samme brik kan efterlade resten af hæren uudviklet. Gentag trækket, når en konkret trussel eller taktik kræver det; overvej ellers en ny brik.",
}

_TOPIC_DA = {"forks": "Gafler", "pins": "Bindinger", "skewers": "Spidninger", "opening": "Åbning", "middlegame": "Midtspil", "endgame": "Slutspil"}
_PIECE_DA = {chess.PAWN: "bonden", chess.KNIGHT: "springeren", chess.BISHOP: "løberen", chess.ROOK: "tårnet", chess.QUEEN: "dronningen", chess.KING: "kongen"}


def localized_exercise(item: dict[str, Any], language: str = "en") -> dict[str, Any]:
    data = dict(item)
    data["description"] = item.get("description", _CONCEPT_INTROS["en"][item["category"]])
    if language != "da":
        return data
    kind = item["criterion"]["kind"]
    objective, explanation = _DANISH[kind]
    data["description"] = _INTRO_DA.get(kind, _CONCEPT_INTROS["da"][item["category"]])
    data.update(title=f"{_TOPIC_DA[item['category']]} · {item['id'].rsplit('-', 1)[-1]}",
                objective=objective, explanation=explanation)
    board = chess.Board(item["fen"])
    first = parse_move(board, item["solution"][0])
    data["hints"] = ["Undersøg skakker, slag og trusler, før du vælger et træk.", objective,
                     f"Se på {_PIECE_DA[board.piece_type_at(first.from_square)]} på {chess.square_name(first.from_square)}.",
                     f"Prøv {board.san(first)}."]
    return data


def retry_feedback(board: chess.Board, move: chess.Move, criterion: dict[str, Any], evidence: dict,
                   language: str = "en") -> str:
    """Explain only an observed failed criterion or an actual analyzed reply."""
    after = board.copy(stack=False)
    after.push(move)
    kind = criterion["kind"]
    da = language == "da"
    if evidence.get("objective_met"):
        reply = (evidence.get("played", {}).get("pv") or [None, None])
        reply = reply[1] if len(reply) > 1 else None
        text = "Mønstret er til stede, men motoranalysen viser en stærkere modstand." if da else "The pattern is present, but engine analysis finds stronger resistance."
        if reply:
            text += f" Undersøg svaret {reply}." if da else f" Examine the reply {reply}."
        return text
    if kind == "fork":
        count = sum(1 for square in after.attacks(move.to_square) if after.color_at(square) == (not board.turn)
                    and VALUES[after.piece_type_at(square)] >= 3)
        if count < 2:
            return (f"Den flyttede brik angriber {count} værdifulde fjendtlige brikker. En gaffel skal angribe mindst to." if da else
                    f"The moved piece attacks {count} valuable enemy pieces. A fork needs at least two targets.")
        if after.is_attacked_by(not board.turn, move.to_square):
            return "Landingsfeltet er angrebet. Find en sikker gaffel." if da else "The landing square is attacked. Look for a safe fork."
        return "Følg den viste fortsættelse, og tag derefter den angrebne brik." if da else "Follow the displayed continuation, then collect the attacked piece."
    messages = {
        "relative_pin": ("Trækket skaber ingen ny relativ binding mod mere værdifuldt materiale.", "This move creates no new relative pin against a more valuable piece."),
        "exploit_pin": ("Trækket udnytter ikke en bundet briks ulovlige genslag.", "This move does not capture on a square whose pinned defender cannot legally recapture."),
        "unpin": ("Trækket ophæver ikke bindingen, mens den bundne brik bliver stående.", "This move does not break the pin while keeping the pinned piece on its square."),
        "defend": ("Behold den truede brik på feltet, og tilføj en forsvarer.", "Keep the threatened piece on its square and add a defender."),
        "outpost": ("Find et fremskudt springerfelt med bondestøtte uden aktuelle fjendtlige bondeangreb.", "Find an advanced knight square with pawn support and no current enemy pawn attack."),
        "simplify": ("Beregn en dronningafbytning med et lovligt genslag, mens du har materialeovervægt.", "Look for a queen exchange with a legal recapture while you are ahead in material."),
        "repair_pawns": ("Find et bondeslag, som reducerer antallet af dobbeltbønder.", "Find a pawn capture that reduces the number of doubled pawns."),
        "opposition": ("Efter trækket skal kongerne stå på samme linje med ét tomt felt imellem.", "After your king move, the kings must face each other with one empty square between them."),
        "hold_corner": ("Din konge når ikke det nødvendige forvandlingshjørne.", "Your king does not reach the required promotion corner."),
        "rook_seventh": ("Find et tårntræk til syvende række set fra din side.", "Find a rook move to the seventh rank from your side."),
        "finish_development": ("Udvikl en let officer fra udgangsrækken, mens dronningen allerede er i spil.", "Develop a minor piece from its original rank while your queen is already in play."),
        "fresh_development": ("Udvikl en ny let officer i stedet for at gentage træk med den udviklede springer.", "Develop a fresh minor piece rather than moving the previously developed knight again."),
        "pin": ("Trækket skaber ingen ny absolut binding foran kongen.", "This move creates no new absolute pin against the king."),
        "skewer": ("Trækket stiller ikke din angriber, kongen og den værdifulde brik på samme linje.", "This move does not line up your attacker, the king, and the valuable piece behind it."),
        "develop": ("Denne opgave kræver udvikling af en springer eller løber fra udgangsfeltet.", "This exercise asks you to develop a knight or bishop from its original rank."),
        "castle": ("Trækket er ikke en rokade. Kontrollér kongens og tårnets muligheder.", "This move is not castling. Check your king and rook options."),
        "center": ("Denne opgave kræver et bondetræk til et af de fire centrale felter.", "This exercise asks for a pawn move into one of the four central squares."),
        "capture": ("Trækket slår ikke en brik af den værdi, opgaven kræver.", "This move does not capture a piece of the value required by the objective."),
        "mate": ("Modstanderen har stadig et lovligt svar; trækket er ikke skakmat.", "The opponent still has a legal reply; this move is not checkmate."),
        "promote": ("Trækket forvandler ikke bonden sikkert. Kontrollér også for pat.", "This move does not promote the pawn safely. Check for stalemate too."),
        "king_activity": ("Opgaven kræver et aktivt kongetræk.", "The objective asks you to activate your king."),
    }
    pair = messages.get(kind, ("Undersøg modstanderens bedste svar, og prøv igen.", "Check the opponent’s strongest reply and try again."))
    return pair[0 if da else 1]
