# Coaching quality benchmark

The frozen [40-position fixture](../tests/fixtures/coaching_benchmark.json) contains expected explanations at beginner, intermediate, and advanced levels: 120 teaching cases. Thirty positions are snapshots of original ChessMate curriculum material; ten additional regression positions cover poisoned captures, forced mates, special moves, stalemate, forced defense, and ambiguous move descriptions. They are legal positions, not a claim of grandmaster annotation or an Elo calibration dataset.

The fixture is independent of the coach output. Changing lesson text or model prompts does not change the expected explanations. Each position records its provenance, legal demonstration line, teaching targets, and examples of unacceptable claims. `test_coaching_benchmark.py` checks the frozen objectives, exact terminal results, ambiguous legal moves, en passant, and underpromotion. In particular, it proves that the poisoned-pawn capture has no immediate legal recapture but still loses to back-rank mate.

## Capture an iteration

```sh
.venv/bin/python scripts/benchmark_coaching.py --output tests/benchmark-results/iteration-01.json
```

The default captures deterministic fallback coaching with real Stockfish. To evaluate a real local model, configure `LLM_BASE_URL`, `LLM_MODEL`, and optionally `LLM_API_KEY` in the process environment, then add `--model`. The command uses environment configuration, not profile-specific saved connections. Credentials are never written into reports. Reports identify the actual response source, latency, word count and fallback reason, so a failed provider cannot silently count as a successful model evaluation.

Long model captures checkpoint each completed position to a `.partial.json` file. Interrupted subsets remain incomplete and cannot pass the full-fixture review gate.

Use `--time-ms 350` consistently when comparing iterations. The report records that budget and the engine version. Engine searches can vary between runs, so compare explanations and confidence as well as rankings. For a small diagnosis, use `--ids poisoned-pawn,underpromotion`; a subset cannot pass the final teaching gate.

Automatic capture checks exact FEN provenance, legal engine continuations, score perspective, supported variations, reachable overlay positions, valid arrows, nonempty answers, and protected hint metadata. Reports include actual visual evidence and hint outputs, and final review rechecks the frozen case identities and evidence rather than trusting edited failure labels. These are safety checks, not an automated measure of teaching quality. A legal but irrelevant answer must still receive a poor teaching score.

## Review the explanations

For every captured row, fill in `review.scores` with all seven dimensions, using integers 0–2:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| accuracy | false concrete claim | ambiguous or overstated | supported, correctly qualified |
| causal_specificity | generic or wrong reason | relevant observation | explains the position-specific cause |
| opponent_response | absent or invented | legal reply with little explanation | relevant reply and its consequence |
| teaching_depth | inappropriate for learner | partly adapted | suitable detail and vocabulary |
| takeaway | missing or misleading | generic principle | useful lesson tied to this decision |
| visual_alignment | wrong/unusable visualization | legal but incomplete demonstration | board explains the stated idea |
| spoiler_discipline | reveals a protected answer | disclosure boundary unclear | respects the requested disclosure |

Set `review.hard_failure` to `true` for any fabricated chess fact, illegal continuation, wrong-position demonstration, or unsolicited protected solution; otherwise set it to `false`. Record the reason in `review.notes`. Review the actual interface to score visual alignment; a JSON line alone does not establish that a beginner can follow the board.

```sh
.venv/bin/python scripts/benchmark_coaching.py --review tests/benchmark-results/iteration-01.json
```

The gate requires every frozen position at all three levels, complete reviews, no hard failures, and a mean score of at least 11/14 at **each** level. Missing reviews fail the gate. Compare per-position failures and per-level means between saved iterations; an improved overall average must not hide a new factual or spoiler regression. The benchmark is currently a regression and evaluation framework, not evidence that a human teaching-quality review has passed.

## Findings from this implementation

The first capture exposed three useful gaps: a poisoned capture showed a mating line while emphasizing material, a pinned-defender capture omitted why recapture was illegal, and underpromotion omitted the stalemate comparison. The implementation now prioritizes terminal consequences, explains the pinned recapturer, and compares the queen-promotion outcome. These have dedicated regressions. The evidence vocabulary now includes pawn structure, files, outposts, space, king safety, activity, pawn levers and qualified candidate effects. The local Qwen run also exposed extra JSON fields and redundant unvalidated prose: the adapter safely normalizes supported selection shapes and discards unsupported wording before rendering canonical evidence. Actual provider sources and corrections are recorded; this does not substitute for independent teaching review.


The completed local Qwen3.6-35B-A3B Q4_K_M run captured all 120 cases: 119 verified model selections, one protected deterministic fallback for invalid model output, and no automatic evidence failures. Median latency was 5.8 seconds and p95 6.85 seconds on this machine. The initial capture, final amended capture and three-level en passant recapture are retained in ignored `tests/benchmark-results/` files. The amended capture records exactly which rows were regenerated and why; the frozen questions/expectations are unchanged. This is structural/provider evidence, with human scores still unfilled.

Reviewing the en passant output showed that a legal generic capture explanation omitted the unusual removal square. The shared move facts/narration now identify the moving pawn, its destination and the separately removed pawn square in both languages and both colors. All three Qwen cases were recaptured after this change. This illustrates a teaching improvement prompted by expected explanations rather than by a new feature count.
