# Coaching improvements

This implementation follows the attached comprehensive coaching brief and the additional requirement that visual teaching is a core capability. Existing game, exploration, review, training, and local inference boundaries remain in place.

## Audit and priorities

| Priority | Existing behavior | Gap and implementation |
| --- | --- | --- |
| P0 | Fact catalog and legal candidate/PV validation | `Selection.response` bypasses factual validation. Require supported explanation composition and reject fabricated model claims. |
| P0 | Legal capture and recapture detection | No immediate recapture incorrectly implies material gain. Describe the observation without promising a tactical gain. |
| P0 | Same-root grading and mate-aware classification | Recheck significant losses; report confidence and uncertainty. |
| P0 | Four progressive hint levels | Early `highlight_move` reveals the answer. Remove move-bearing evidence until its disclosure level. |
| P1 | Candidate previews and isolated exploration | Add a shared visual variation player with controls, accessible arrows, and explicit return to the saved position. |
| P1 | Feedback, conversation, review, personal exercises | Share structured position-bound insights and variations across these consumers. |
| P1 | Automatic or manually triggered computer replies | Expose coach-first play and retry/calculation workflows without changing saved games. |
| P2 | Bounded cached Stockfish analysis | Add explicit quick/deep budgets, critical-position rechecks, full-game analysis and candidate comparison. |
| P3 | Topic progress, scheduled exercises, preferences | Improve category adaptation, independent-solution tracking, multi-move lessons, and teaching preferences. |
| Quality | Legal curriculum with recorded engine evidence | Add 40 frozen benchmark positions with expected explanations at beginner, intermediate, and advanced levels; measure teaching separately from factual validity. |

## Verification gates

1. Regression tests reject fabricated claims, illegal variations, wrong provenance, and early visual spoilers.
2. Board previews replay legally and never submit game mutations; controls work by pointer and keyboard.
3. Existing backend/frontend suites and the production frontend build continue to pass.
4. Browser journeys verify visual playback and persisted game isolation on desktop and touch layouts.
5. Run the frozen coaching benchmark and retain position/level/source and human-review scores. Passing structural checks is not a claim that teaching quality passed.
6. Test a real configured local model when available; record its availability and results without disclosing credentials.

## Benchmark acceptance

Each explanation is reviewed for factual accuracy, causal specificity, useful opponent response, appropriate teaching depth, actionable takeaway, visual alignment, and spoiler discipline. Score each dimension from 0 (missing/incorrect), 1 (partial), to 2 (clear and correct). Any concrete false chess claim, illegal continuation, wrong-position visualization, or unsolicited answer in a protected hint is a hard failure regardless of total score. Compare iterations on the same positions and settings. Require no hard failures and an average of at least 11/14 at each teaching level before claiming benchmark teaching quality is satisfactory. Record failures and regressions, including safe but unhelpful generic answers.

## Implemented scope and verification limits

| Area | Result |
| --- | --- |
| Unchecked model prose | Closed the bypass; evidence segments and dynamic causal facts compose grounded narration. Fully unrestricted natural-language factual reasoning remains outside this safety boundary. |
| Material and move assessment | Conservative capture wording, pinned recapturer checks, terminal outcomes, causal changes in support/attacks/pins, same-root significant-loss rechecks, confidence and uncertainty. |
| Board teaching | Shared isolated legal variation player, accessible arrows/targets, candidates, feedback, live chat, hints, review and solved lessons. |
| Hints and spoilers | Early hints omit move-bearing metadata; alternative evidence and hidden best-move references are filtered. |
| Retry | Confidently verified game mistakes become private exercises with normal attempt/hint/independence tracking; arbitrary positions can still be explored independently. |
| Calculation | Entire predicted line validated, every ply assessed, first weaker decision/response identified, final evaluation compared when supplied. Immutable calculation events contribute per-ply accuracy, response errors, final-position assessment, hints, retries, independence, topic mastery, and replayable history. |
| Play pace | Automatic, coach-first and independent pace controls; legacy automatic-reply opt-outs preserved. |
| Analysis | Independent quick/deep workers; owned, bounded, cancellable background jobs; full-game both-side analysis with deeper critical-position verification; resulting-position comparisons and legal continuations. Pawn structure, activity, king safety, space, files, outposts, pawn levers, exchanges, prophylaxis, and endgame transitions distinguish observations from interpretations. |
| Learning | Recent topic mastery, seven observed skills, independent/assisted solves, repeated errors, adaptive sessions, branch-specific hints and reverified game-derived multi-move exercises; 84 curated lessons including 20 new 3–7-ply lines. Later live-game decisions link only to earlier completed practice with matching positions or verified patterns; associations do not establish causation. |
| Benchmark | Frozen 40 positions, 120 expected explanations, real-Stockfish capture, adversarial/special-rule regressions and a complete-review teaching gate. Real local Qwen evaluation records actual model/fallback sources. Independent human teaching scores remain unfilled and cannot pass the quality gate. |
| Deployment | Local-first trusted profiles remain the default. Optional authenticated mode adds password provisioning, secure cookie sessions, ownership enforcement, login/registration throttles, session revocation and password changes. Server-side inference credentials and loopback deployment remain available. |

| Discovery and saved explanations | Persistent FEN-bound notice/identify/calculate/evaluate/reflect dialogue, checked learner discoveries, escalating help, guided/direct switching, and exact saved text/visual/evidence payloads. |
| Presentation preferences | Text/board/both, independent arrow/threat/piece highlights, animation, speed, automatic return, teaching presets and explicit overrides. |

The requested software workflows are implemented. Factual generation deliberately remains grounded in inspectable board/engine evidence: unsupported model prose is discarded, never trusted because it cites a fact. This is not a general proof system for arbitrary chess commentary. Independent human teaching review, longitudinal learner improvement, precise opponent Elo calibration, and physical Safari/iOS testing remain external validation work. The benchmark makes these limits visible instead of treating legal output as proof of good teaching.
