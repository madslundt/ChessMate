import chess
import pytest

from src.backend.chess_tools import observations, parse_board, parse_move


def test_castling_and_check():
    board = parse_board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    board.push(parse_move(board, "O-O"))
    assert board.king(chess.WHITE) == chess.G1
    assert board.piece_at(chess.F1).piece_type == chess.ROOK
    board = parse_board("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1")
    assert board.is_check()
    with pytest.raises(ValueError): parse_move(board, "e1e3")


@pytest.mark.parametrize("color", [chess.WHITE, chess.BLACK])
def test_en_passant(color):
    from src.backend.chess_tools import move_facts, move_idea
    board = parse_board(chess.STARTING_FEN, ["e4", "a6", "e5", "d5"])
    if color == chess.BLACK: board = board.mirror()
    move = parse_move(board, "exd6" if color else "exd3")
    assert board.is_en_passant(move)
    victim = "d5" if color else "d4"
    facts = move_facts(board, move)
    assert facts["en_passant"] and facts["captured_square"] == victim
    assert victim in move_idea(facts) and "removes" in move_idea(facts)
    assert victim in move_idea(facts, "da") and "fjerner" in move_idea(facts, "da")
    board.push(move)
    assert board.piece_at(chess.parse_square(victim)) is None


def test_en_passant_reply_counts_as_a_capture_of_the_moved_pawn():
    from src.backend.chess_tools import move_facts
    board = parse_board("7k/8/8/8/3p4/8/4P3/K7 w - - 0 1")
    facts = move_facts(board, board.parse_san("e4"))
    assert "dxe3" in facts["legal_reply_captures"]


@pytest.mark.parametrize("promotion", ["q", "r", "b", "n"])
def test_promotions(promotion):
    board = parse_board("7k/P7/8/8/8/8/8/K7 w - - 0 1")
    board.push(parse_move(board, "a7a8" + promotion))
    assert board.piece_at(chess.A8).symbol().lower() == promotion


def test_checkmate_stalemate_insufficient_material():
    mate = parse_board(chess.STARTING_FEN, ["f3", "e5", "g4", "Qh4#"])
    assert mate.is_checkmate() and mate.result() == "0-1"
    stalemate = parse_board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert stalemate.is_stalemate()
    assert parse_board("7k/8/6K1/8/8/8/8/8 w - - 0 1").is_insufficient_material()


def test_repetition_and_fifty_moves():
    board = parse_board(chess.STARTING_FEN, ["Nf3", "Nf6", "Ng1", "Ng8"] * 2)
    assert board.can_claim_threefold_repetition()
    board = parse_board("7k/8/6K1/8/8/8/R7/8 w - - 100 70")
    assert board.can_claim_fifty_moves()


def test_invalid_fen_null_move_and_illegal_move_rejected():
    for fen in ("nonsense", "8/8/8/8/8/8/8/8 w - - 0 1"):
        with pytest.raises(ValueError): parse_board(fen)
    for move in ("e2e5", "0000", "--", "Qh5"):
        with pytest.raises(ValueError): parse_move(chess.Board(), move)


def test_absolute_pin_is_verified_and_geometry_is_qualified():
    board = parse_board("4r1k1/8/8/8/8/8/4B3/4K3 w - - 0 1")
    assert observations(board)["absolute_pins"][0]["square"] == "e2"


def test_checking_fork_requires_a_legal_queen_capture_after_every_reply():
    board = parse_board("2q5/5k2/8/5N2/8/8/8/4K3 w - - 0 1")
    forks = observations(board)["verified_short_forks"]
    assert any(item["uci"] == "f5d6" and item["verified_replies"] > 0 for item in forks)
    # A rook can capture the checking knight: the apparent fork is not verified.
    defended = parse_board("2q5/3r1k2/8/5N2/8/8/8/4K3 w - - 0 1")
    assert not any(item["uci"] == "f5d6" for item in observations(defended)["verified_short_forks"])


def test_skewer_geometry_is_labeled_unverified():
    board = parse_board("q7/k7/8/8/8/8/8/R3K3 b - - 0 1")
    skewers = observations(board)["geometric_skewers"]
    assert any(item["attacker"] == "a1" and item["front"] == "a7" and item["behind"] == "a8" for item in skewers)
    assert all("unverified" in item["meaning"] for item in skewers)


def test_deterministic_tools_preserve_board_and_history():
    from src.backend.chess_tools import get_position, get_legal_moves, get_move_history, get_threats
    board = parse_board(chess.STARTING_FEN, ["e4", "e5", "Nf3"])
    fen = board.fen()
    assert get_position(board)["fen"] == fen
    assert any(m["san"] == "Nc6" for m in get_legal_moves(board))
    assert [m["san"] for m in get_move_history(board)] == ["e4", "e5", "Nf3"]
    assert get_threats(board)["fen"] == fen
    assert board.fen() == fen


def test_natural_move_resolution_handles_destination_and_capture_without_guessing():
    from src.backend.chess_tools import resolve_move_references
    board = chess.Board()
    assert resolve_move_references(board, "What if I move my knight to c3?")["moves"] == ["b1c3"]
    board = chess.Board("4k3/8/8/8/8/8/8/1N1NK3 w - - 0 1")
    result = resolve_move_references(board, "What if I move my knight to c3?")
    assert not result["moves"] and len(result["ambiguous"][0]["choices"]) == 2
    assert resolve_move_references(board, "Move my knight from b1 to c3")["moves"] == ["b1c3"]


def test_unrecapturable_capture_does_not_claim_a_verified_material_gain():
    from src.backend.chess_tools import move_facts, move_idea
    board = chess.Board("6k1/5ppp/8/8/8/q7/1P3PPP/4R1K1 b - - 0 1")
    facts = move_facts(board, board.parse_san("Qxb2"))
    assert facts["capture"] and not facts["legal_reply_captures"]
    assert "gaining material" not in move_idea(facts)
    assert "du vinder materiale" not in move_idea(facts, "da")


def test_pinned_defender_and_underpromotion_have_specific_explanations():
    from src.backend.chess_tools import move_facts, move_idea
    board = chess.Board("4k3/pp6/2n5/1B2p3/3P4/8/PP4K1/8 w - - 0 1")
    facts = move_facts(board, board.parse_san("dxe5"))
    assert facts["pinned_recapturers"] == ["c6"]
    assert "pinned to its king" in move_idea(facts) and "c6" in move_idea(facts)
    board = chess.Board("8/k1P5/2K5/8/8/8/8/8 w - - 0 1")
    rook = move_facts(board, board.parse_san("c8=R"))
    queen = move_facts(board, board.parse_san("c8=Q"))
    assert rook["underpromotion_avoids_stalemate"] and queen["stalemate"]
    assert "avoids the stalemate" in move_idea(rook)


def test_variation_frames_handle_castling_en_passant_promotion_and_mate():
    from src.backend.chess_tools import variation_evidence
    examples = [("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", ["O-O", "O-O-O"]),
                (chess.STARTING_FEN, ["e4", "a6", "e5", "d5", "exd6"]),
                ("7k/P7/8/8/8/8/8/K7 w - - 0 1", ["a8=R+"]),
                (chess.STARTING_FEN, ["f3", "e5", "g4", "Qh4#"])]
    for fen, moves in examples:
        board = parse_board(fen)
        evidence = variation_evidence(board, moves)
        replay = board.copy()
        for frame in evidence["frames"]:
            assert frame["before_fen"] == replay.fen()
            replay.push(parse_move(replay, frame["uci"]))
            assert frame["fen"] == replay.fen()
        assert evidence["resulting_fen"] == replay.fen() and board.fen() == fen
    assert evidence["terminal"] == "checkmate" and evidence["winner"] == "black"


def test_before_after_geometry_distinguishes_new_exposure_from_existing_threats():
    from src.backend.chess_tools import move_facts
    board = chess.Board("4r1kr/8/8/8/7P/2N5/4Q3/6K1 w - - 0 1")
    facts = move_facts(board, board.parse_san("Nb5"))
    assert [item["square"] for item in facts["newly_exposed_own"]] == ["e2"]
    assert "e2" in [item["square"] for item in facts["removed_geometric_support"]]
    # h4 was already attacked and undefended; moving the knight did not cause that problem.
    assert "h4" not in [item["square"] for item in facts["newly_exposed_own"]]


def test_new_double_attack_and_new_pin_are_position_bound_geometry():
    from src.backend.chess_tools import move_facts, relation_idea
    board = chess.Board("2q5/5k2/8/5N2/8/8/8/4K3 w - - 0 1")
    facts = move_facts(board, board.parse_san("Nd6+"))
    assert {item["square"] for item in facts["created_geometric_double_attack"]} == {"c8", "f7"}
    assert "material win still needs verification" in relation_idea(facts)
    board = chess.Board("4k3/8/2n5/4p3/8/8/4B3/6K1 w - - 0 1")
    facts = move_facts(board, board.parse_san("Bb5"))
    assert any(item["square"] == "c6" for item in facts["new_absolute_pins"])
