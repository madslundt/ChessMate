"""Meaning-preserving paraphrase checks for dynamic chess evidence.

Model wording can vary through approved equivalent expressions and harmless teaching
framing. Adding, negating or strengthening a board claim is rejected. This deliberately
does not pretend that lexical overlap verifies an arbitrary factual explanation.
"""
import re
from collections import Counter


EQUIVALENCES = (
    (r"\b(?:straight away|immediately)\b", "immediately"),
    (r"\b(?:permitted|legal)\b", "legal"),
    (r"\b(?:under attack|attacked)\b", "attacked"),
    (r"\b(?:without a geometric defender|geometrically undefended)\b", "geometrically undefended"),
    (r"\b(?:this particular variation|this specific line|this specific continuation)\b", "this specific line"),
    (r"\b(?:prior to|before)\b", "before"),
    (r"\b(?:consider|think about)\b", "consider"),
    (r"\b(?:check whether|verify whether)\b", "check whether"),
    (r"\b(?:does not prove|does not establish)\b", "does not prove"),
    (r"\b(?:is now absolutely pinned to its king|is now pinned to its king)\b", "is now absolutely pinned to its king"),
    (r"\b(?:in this search|in the current search)\b", "in this search"),
    (r"\b(?:with no immediate legal recapture|without an immediate legal recapture)\b", "with no immediate legal recapture"),
    (r"\b(?:undersøg|tjek)\b", "undersøg"),
    (r"\b(?:netop denne variant|denne specifikke variant)\b", "netop denne variant"),
)
TEACHING_PREFIXES = ("Let's work through that. ", "Here is the key observation: ", "For your calculation: ",
                     "Keep this in mind: ", "To explore your idea, consider this: ", "Lad os undersøge det. ", "Bemærk: ")


def normalize_evidence(text: str) -> str:
    for pattern, replacement in EQUIVALENCES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return " ".join(re.sub(r"[.,:;!?]", " ", text).lower().split())


def verified_paraphrase(text: str, evidence: str) -> str:
    value = text.strip()
    for prefix in TEACHING_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    # Preserve notation case: Bxe4 and bxe4 can denote different legal moves.
    notation = r"\b(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|[a-h](?:x[a-h])?[1-8](?:=[QRBN])?[+#]?|O-O(?:-O)?[+#]?)"
    if Counter(re.findall(notation, value)) != Counter(re.findall(notation, evidence)):
        raise ValueError("Paraphrase changes board references or move notation")
    if normalize_evidence(value) != normalize_evidence(evidence):
        raise ValueError("Paraphrase changes a factual claim or its qualification")
    return text.strip()
