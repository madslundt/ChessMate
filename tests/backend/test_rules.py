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


def test_en_passant():
    board = parse_board(chess.STARTING_FEN, ["e4", "a6", "e5", "d5"])
    move = parse_move(board, "exd6")
    assert board.is_en_passant(move)
    board.push(move)
    assert board.piece_at(chess.D5) is None


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
