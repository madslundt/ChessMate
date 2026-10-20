import pytest

from src.backend.coaching_language import verified_paraphrase


def test_natural_paraphrase_preserves_dynamic_evidence_and_qualifications():
    evidence = "This captures a pawn with no immediate legal recapture on b2. Check the opponent's other threats before treating the material as won."
    natural = "Here is the key observation: This captures a pawn without an immediate permitted recapture on b2. Check the opponent's other threats prior to treating the material as won."
    assert verified_paraphrase(natural, evidence) == natural


@pytest.mark.parametrize("false_text", [
    "The knight on f3 is safe.",
    "The knight on f3 is not attacked.",
    "The knight on c3 is attacked.",
    "The knight on f3 is attacked, so Black wins a queen.",
])
def test_paraphrase_rejects_strengthening_negation_wrong_square_and_new_conclusion(false_text):
    with pytest.raises(ValueError): verified_paraphrase(false_text, "The knight on f3 is attacked.")


def test_paraphrase_cannot_change_bishop_notation_to_pawn_capture():
    with pytest.raises(ValueError): verified_paraphrase("Try bxe4.", "Try Bxe4.")


def test_qualification_cannot_be_removed_even_with_high_word_overlap():
    with pytest.raises(ValueError):
        verified_paraphrase("At the end of this particular variation, you gain material.",
                            "At the end of this specific line, you gain material. Other replies may change the result.")
