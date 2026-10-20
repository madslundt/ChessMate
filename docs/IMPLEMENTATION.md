# Implementation and verification record

Updated: 20 October 2026. Final source and verification record. Unchecked environment-dependent checks are not claims of completion. Source implementation, automated verification, and real deployment verification are recorded separately.

## Comprehensive coaching implementation — 20 October 2026

This section is the current source and verification record. Older phases below preserve historical decisions and test counts; they are superseded here.

Implemented:

- Evidence-grounded coaching with causal changes in attacks, defenders, pins, double attacks and skewers; terminal results, illegal recaptures, promotion/stalemate comparisons and conservative material claims. Supported model selections survive discarded unsupported wording; unchecked prose never reaches the answer. Meaning-preserving paraphrases use inspected equivalence rules.
- Fixed learner/actor perspective, natural-language move resolution, board selection for ambiguity, historical pre-move context, short/deep grading confidence and same-root rechecks. The practice opponent samples searched candidates rather than arbitrary legal errors; levels are not calibrated Elo.
- Visual teaching throughout feedback, hints, live/saved conversations, candidates, review and solved lessons: FEN-bound arrows/highlights, isolated legal playback, reversible transport, speed, return, candidate result comparisons and consequence/alternative views. Preview-only lines cannot mutate games. Early hints exclude move-bearing evidence.
- Automatic, coach-first and independent play; private tracked retry; board-based calculation of a candidate, opponent replies and further moves, every-ply accuracy, first-error and final-position feedback, revision-checked first-candidate commit and replayable history.
- Persistent Socratic notice/identify/calculate/evaluate/reflect state; verified discoveries and simple learner conclusions, escalating help, guided/direct switching, exact saved text/visual/evidence payloads and optimistic concurrency.
- Separate quick/deep Stockfish workers and bounded owned background jobs: one job worker, four slots, two active jobs per profile, actual UCI cancellation and bounded caching. Whole-game review covers both sides of imports/completed games, deep-verifies critical positions with a 5–20-second budget and commits only against the starting revision. A 15-minute work window supports partial resume.
- Inspectable pawn structure, backward/outpost candidates, files, space, king safety, activity and pawn levers, plus qualified exchange, prophylaxis and endgame-transition effects. The UI separates board facts from strategic interpretation and compares resulting positions without exaggerating equivalent candidates.
- Immutable calculation learning events, topic mastery, seven granular observed skills, independent/assisted outcomes, hints/retries and repeated errors. Subsequent actual player move events can match earlier completed practice by position or verified motif; imported/analysis/opponent moves and unreliable grades do not establish transfer.
- 84 curated exercises including 20 new 3–7-ply defensive/planning/exchange/endgame lessons; sound later-ply alternatives, branch-specific hints and fresh per-ply verification; adaptive personal game lines can extend to nine plies and stop once the teaching consequence is visible.
- Beginner/intermediate/advanced presets with explicit overrides; text/board/both presentation, independent piece/threat/arrow preferences, animation, speed and automatic return.
- Optional authenticated deployment using existing password/session tables: interactive provisioning/recovery, salted password hashes, HttpOnly SameSite cookie sessions, expiry/rotation/revocation, password changes, account isolation and bounded attempt limits. Trusted local passwordless profiles remain compatible. Inference keys stay server-side; the proxy replaces client-supplied forwarding identity.
- Additive migration `28e4cdfddcb2` adds coaching evidence, versioned discovery state and learning events; existing games/preferences remain compatible.
- Frozen 40-position/120-case teaching benchmark with actual explanation, engine, visual, protected-hint, latency, word-count and provider-source capture, interrupted-run checkpoints, frozen-case validation and a complete-review quality gate.

Principal changed components:

| Boundary | Files and components |
| --- | --- |
| Evidence and coaching | `chess_tools.py`, `coach.py`, `coach_facts.py`, `coaching_language.py`, `coaching_state.py`, `coaching_strategy.py`, `coaching_persistence.py`, `coaching_models.py` |
| Engine, games and API | `engine.py`, `analysis_jobs.py`, `fullgame_analysis.py`, `calculation.py`, `games.py`, `main.py`, `schemas.py`, `views.py` |
| Learning | `training.py`, `training_progress.py`, `training_attempts.py`, `training_generation.py`, `learning_evidence.py`, `learning_models.py`, `exercises.py`, `exercise_library.json` |
| Board and visual UI | `Board`, `GameWorkspace`, `useGameWorkspace`, `exploration`, `VariationPlayer`, `VisualExplanation`, `CandidateList`, `CandidateComparison`, `ConsequenceComparison`, `CalculationBoard`, `CalculationPractice` |
| Coaching, review and learning UI | `CoachPanel`, `CoachMessages`, `useCoachSession`, `SocraticProgress`, `GameReview`, `useFullGameAnalysis`, `BlunderReview`, `Learn`, `LearningProgress`, `CalculationHistory`, `CoachingPreferences`, English/Danish locales |
| Account security and deployment | `auth.py`, `profile_security.py`, `secure_profiles.py`, `manage_accounts.py`, `SecureProfileAccess`, `AccountSecurity`, `App`, `api`, environment/Compose/Nginx/backend image configuration |
| Migration and quality | `28e4cdfddcb2_coaching_and_learning_evidence.py`, `benchmark_coaching.py`, `validate_exercises.py`, `expand_curriculum.py`, frozen fixture, backend/unit/browser regressions |

Current verification:

| Check | Result |
| --- | --- |
| Backend regression | 241 tests passed in the final nonroot, read-only, network-disabled Python 3.12/Stockfish 17 production image (38.97 seconds). Earlier local Python 3.14 coverage and focused provider/history/cancellation regressions also passed; only existing deprecation warnings remain |
| Frontend production build, lint and Vitest | Passed; 26 unit tests passed |
| Browser regression | 177/177 passed in a clean final desktop/tablet/mobile run (5.4 minutes), including secure registration/login/reload/password change/logout/ownership. HTML report preserved at /tmp/chessmate-all-final-green-report/index.html. Twelve focused final integration variants also passed |
| PostgreSQL | Fresh isolated cluster: upgrade/check/downgrade-base/upgrade/check, no drift; account isolation, CAS conflicts, real Stockfish, exploration, practice, repertoire and durable coaching passed |
| Curriculum | All 84 lessons passed fresh Stockfish 19 and deployed Stockfish 17 validation, including every authored continuation ply |
| Real local model | Qwen3.6-35B-A3B Q4_K_M served temporarily on loopback with llama-server; 120 cases captured: 119 validated model responses, one safe invalid-response fallback, zero automatic failures; median 5.8 seconds, p95 6.85 seconds. En passant was recaptured at all three levels after improving its explanation; the original full capture and amendment provenance are retained |
| Benchmark teaching gate | Human reviews remain unfilled; missing reviews correctly cannot establish teaching-quality acceptance |
| Dependency security | `npm audit --omit=dev` and `uvx pip-audit -r src/backend/requirements.lock`: no known vulnerabilities |
| Prescribed scanner | Attempted; npm 404 for unavailable/invalid package `@Codex-flow/cli`. No successful result claimed for that tool |
| Compose, whitespace and file boundaries | Configuration and diff checks passed; changed source files stay below 500 lines |
| Running local deployment | Private pre-upgrade database backup created; final images rebuilt and healthy on loopback port 8080, migration at 28e4cdfddcb2. Eight new production browser workflows, final real-Qwen SSE, exact running-source hash comparison for all 42 backend/data/utility files, and private-cache/offline PWA checks passed. Full-stack stop/start passed nine seed groups, four persistence/resume groups and disposable-profile cleanup |

A final review also fixed FEN-only chat losing repetition history: game-bound coaching now reconstructs only the selected historical move stack and explicit variation, recognizes repetition draws, and excludes future actual moves. Terminal discovery asks for a lesson from the finished position.

Live Qwen evaluation found failures that compatible-provider fixtures missed: redundant unchecked prose and extra `text` fields in structured selections. The adapter discards unsupported text, preserves only validated fact selections and explicitly labels corrected grounding. A shorter disclosure-aware context and minimal selection prompt reduced requests from roughly 30 seconds to about four seconds in focused smoke checks; the full capture median was 5.8 seconds. A regression also reproduced and fixed a queued-request cancellation leaking model capacity. Waiting for a model slot is now cancellation-safe. This measures this model/quantization/host, not DGX Spark performance.

Try it: choose **Coach first**, make a move, open **Show on board**, compare candidates, and use **Calculate before moving** to play a predicted branch without changing the game. A verified mistake offers **Retry this position** as tracked private practice. In Analyze, **Analyze all moves** starts cancellable background review; **Deep analysis** uses the separate long-search worker. Switch guided/direct explanations in chat, reload to resume discovery and saved visual evidence, then inspect Progress for calculation replay, topic skills and later matching game decisions. Settings controls skill presets, visual presentation and playback. Account security is enabled explicitly through the setup guide.

The requested software scope is implemented. Final engine validation also caught an intermittent distant-mate versus centipawn search disagreement in an already losing opponent continuation. A bounded third search must converge under the unchanged objective/depth/equivalence rules; unresolved evidence is still rejected. Six fresh deployed-engine repetitions passed. Independent human teaching review and longitudinal learning improvement remain unmeasured, opponent strength is not Elo-calibrated, and physical Safari/iOS devices have not been tested. Open-ended model prose remains deliberately constrained by verified evidence. Temporary model evaluation did not change saved user inference settings. The temporary model server, password-mode test server and test secret were removed after verification; the normal development servers and rebuilt Compose application remain available. These validation limits are not represented as passed quality gates.

## Earlier build decisions and dependencies (historical)

- Empty starting repository; React/TypeScript/Vite frontend and FastAPI/Python backend.
- Git initialized on `main`; `origin` fetch/push URL is `https://github.com/madslundt/ChessMate.git`. Clone and existing-folder setup instructions are in [README.md](README.md#repository-setup).
- PostgreSQL in deployment; SQLite supports isolated local development and tests.
- Stockfish executes in the backend container; a configurable local model may run on another machine.
- No paid inference service, hardcoded model name, mandatory external chess database, or telemetry.
- Local accounts and persisted opaque sessions; same-origin API proxy for deployment.
- Revision-checked game commands and append-only game actions; exploration remains separate from authoritative state.
- Deployment needs Docker Compose and a reachable Docker daemon; live inference needs the user's own served model.
- Exact backend versions are pinned in `src/backend/requirements.lock` and installed by Docker; direct ranges remain in `requirements.txt`. Frontend dependencies use `package-lock.json` and `npm ci`.

## Phase 1 — Foundation

- [x] Inspect repository and applicable parent instructions.
- [x] Define frontend/backend/engine boundaries and deployment configuration.
- [x] Complete backend schemas, authentication, persistence models, and migrations.
- [x] Typed Pydantic response models for core auth, game, analysis, exercise, progress, and settings APIs, with validated OpenAPI schemas.
- [x] Complete bounded Stockfish service and authoritative chess state.
- [x] Run SQLite and isolated PostgreSQL 17 migration upgrade/check/downgrade/upgrade/check and account isolation checks; actual Compose PostgreSQL reached migration `3419be9c3cd5` and seeded all 64 exercises.

## Phase 2 — Gameplay and analysis

- [x] Play as either side with an adjustable legal computer opponent.
- [x] Autosave, history, resume, PGN export/import, and FEN analysis.
- [x] Show legal moves, promotion, check/endings, move navigation, and undo.
- [x] Compare played moves against same-root candidates with correct score perspective.
- [x] MultiPV candidates, hypothetical variations, undo/reset, and safe commit.
- [x] Verify stale revision rejection and hypothetical state isolation in backend tests.

## Phase 3 — Coaching

- [x] Structured, position-bound context and legal move-reference validation.
- [x] Configurable local inference endpoint/model/credentials/timeouts.
- [x] Streamed answers, bounded requests, malformed-response handling, and offline fallback.
- [x] Progressive hints, independent/guided/learning/Socratic modes, and spoiler settings.
- [x] Verified proactive guided observations, phase-specific learning explanations, and persisted position-bound conversations.
- [x] Test LLM failure, stale context, illegal references, deterministic output, and streamed-adapter JSON validation with deterministic HTTP/SSE responses.
- [x] Seventeen bilingual regressions distinguish learner color from side to move for paused-computer checks, castling, candidates, material, and hints.

The local model selects identifiers from a verified sentence catalog using JSON. Candidate moves and principal variation references are checked before display. The server buffers model deltas until the selection passes validation, then emits validated text chunks over SSE. Arbitrary free-form model prose is not displayed. This is an intentional accuracy boundary and limits conversational breadth to implemented evidence statements; it is not an unrestricted natural-language chess reasoner.

## Phase 4 — Training

- [x] Interactive exercise engine and objective-based alternative solutions.
- [x] 64 original exercises: 12 forks, 11 pins, eight skewers, ten opening, 12 middlegame, and 11 endgame positions.
- [x] Two actual three-ply puzzles, one two-ply solution, and single-decision teaching positions for other entries.
- [x] Expanded concepts: relative/exploited/broken pins, defense, activity, outposts, simplification, pawn structure, opposition, draws, rooks on the seventh rank, and opening discipline.
- [x] Record valid FENs, side, objective, solutions, difficulty, hints, tags, and explanation.
- [x] Verify all intended exercises with python-chess and Stockfish, with stored analysis evidence.
- [x] Provide an extensible validated import flow via `scripts/import_exercises.py`; verified `--replace` updated all 64 public seeds.
- [x] Private white/black opening repertoire interface/storage, legal line normalization, deletion, and Stockfish-verified practice generation.

## Phase 5 — Learning and progress

- [x] Persist attempts, hint use, topics, and training sessions.
- [x] Target weak topics and schedule missed exercises for repetition.
- [x] Generate evidence-backed exercises from instructive game mistakes, with fresh engine checks and account ownership.
- [x] Post-game summary with revisitable positions and recommendations.
- [x] Progress screen and five-minute daily/ten-minute mixed, tactical, opening, endgame, review, mistake, and category session selection.

## Phase 6 — UI, deployment, and verification

- [x] Responsive board, touch interaction, loading/error states, keyboard interaction, and mobile logout.
- [x] English/Danish interface and independent coach language settings.
- [x] Visible English/Danish dark/light theme switch, persisted settings, live system appearance changes, dark contrast, PWA manifest, and build-versioned service worker.
- [x] Automatic computer turns enabled by default; saved opt-outs preserved, retries bounded by game/revision, and current profile enabled.
- [x] Production PWA first-visit JavaScript/CSS caching, private-API exclusion, and offline shell reload verified.
- [x] Dockerfiles, private database network, persistent volume, nonroot services.
- [x] Migration job, health checks, same-origin reverse proxy, SSE buffering disabled.
- [x] Server-only LLM configuration and secret-free environment example.
- [x] Start/check scripts and installation/architecture/evaluation documentation.
- [x] Run backend automated tests: 105 passed inside the production nonroot/read-only Python 3.12/Stockfish 17 container in 18.26 seconds, including automatic-reply defaults and preserved opt-outs.
- [x] Run frontend production build and seven Vitest unit tests.
- [x] Run 15 production Playwright acceptance scenarios across desktop, mobile, and tablet through the rebuilt Compose stack; all passed in 1.3 minutes, including automatic replies and persisted theme switching.
- [x] Validate Docker Compose configuration.
- [x] Build Docker images; migrations exit zero and frontend/backend/PostgreSQL become healthy.
- [x] Inspect runtime restrictions: all three services nonroot, all capabilities dropped, no new privileges; app filesystems read-only; only frontend bound at `127.0.0.1:8080`.
- [x] Stop frontend/backend/database, start again with `up --wait`, and verify exact saved state through real HTTP (nine seed groups and four resume groups).
- [x] Verify compatible-provider HTTP/SSE protocol and fallback using separate temporary provider/backend containers, with exact board/learner/candidate/variation checks.
- [x] Real local Qwen inference subsequently verified; see the current coaching record above.

## Original verification evidence (historical)

| Check | Actual result |
| --- | --- |
| `sh -n scripts/start.sh scripts/check.sh` | Passed |
| `docker compose --env-file config/.env.example -f config/compose.yaml config --quiet` | Passed |
| Nginx backend DNS recovery | Isolated Docker regression reproduced the original failure after a backend IP change (no recovery within 20 seconds), then passed with dynamic upstream resolution: API/docs/OpenAPI recovered in 6.37 seconds without restarting the proxy/master. Temporary containers/network were removed |
| Docker daemon recovery | Initial daemon calls hung; a normal restart did not recover it. Docker Desktop force-stop/start restored the API. Actual image builds and runtime checks then completed successfully |
| Compose build/start and restrictions | Frontend/backend images built; migration job exited 0 at `3419be9c3cd5`; all 64 exercises seeded; frontend/backend/PostgreSQL healthy. Nonroot/cap-drop-all/no-new-privileges verified for all services, read-only application filesystems, and only loopback port 8080 published. Generated `config/.env` mode 0600 |
| Backend container tests | 105 passed in 18.26 seconds inside the production nonroot, read-only, network-disabled Python 3.12/Stockfish 17 image, including automatic-reply default/opt-out, expanded curriculum, account/position consistency, typed API responses, adapter cases, and 17 bilingual learner-perspective regressions |
| Combined check script | `scripts/check.sh` passed: backend tests, frontend production build, seven Vitest tests, and Compose validation |
| Alembic migrations | SQLite and isolated PostgreSQL 17 upgrade/check/downgrade-base/upgrade/check passed without drift; actual Compose PostgreSQL reached final revision `3419be9c3cd5` |
| PostgreSQL application integration | `scripts/check_postgres.py` passed against final typed-response/perspective source and the 64-exercise library on disposable PostgreSQL 17: auth/account isolation, saved legal games, two-session CAS/stale conflicts, real Stockfish analysis/computer/undo, exploration, hints/attempts/progress, training, white/black repertoire practice, and durable coaching/resume. Socket-only cluster stopped and removed afterward |
| Frontend production build | Passed |
| Frontend unit tests | Seven passed |
| Frontend dependency audit | `npm audit` reports zero known vulnerabilities after the Vitest update |
| Browser Compose scenarios | All 15 Playwright scenarios passed in 1.3 minutes through the rebuilt Compose stack: desktop 1488 × 1058, iPad Mini, and iPhone 13 Chromium emulation. Covers automatic White/Black replies exactly once, failed-engine single attempt/manual recovery, pending timer cancellation, Explore/history/analysis isolation, persisted dark/light switching, plus the previous gameplay/coaching/training/repertoire scenarios with explicit manual opt-out |
| Supplemental deployed training | Desktop and mobile checks passed for exercises/hints/progress and both white/black repertoire practice through the running stack |
| Production PWA | Strengthened `tests/e2e/verify-pwa.mjs` passed on Compose port 8080: bounded first-visit service-worker control, precached JS/CSS, authenticated private API responses excluded from every cache, and successful offline shell reload |
| Real HTTP persistence/restart | Nine seed groups and four resume groups passed across a full frontend/backend/database stop and `up --wait`: original cookie authentication, exact games/revisions/move evidence, PGN/promotion, preferences, exact-FEN conversations, review, idempotent seeds, engine availability, and session revocation persisted/worked |
| Compatible-provider protocol | Isolated real Docker provider/backend HTTP/SSE check passed: verified streamed selection produced `local_llm_verified` in 0.62 seconds; malformed JSON, illegal move/PV, and timeout (1.02 seconds) fell back deterministically. Exact FEN, learner/root color, legal moves, requested Nf3, and legal engine PV checked on all four requests; Stockfish remained operational. Temporary resources removed |
| Full curriculum and import | All 64 positions freshly verified again inside the deployed Stockfish 17 backend with `python scripts/validate_exercises.py --require-curriculum --seconds 0.3`; every objective and intended solution passed. CLI `--replace` was previously tested and public seeds updated |
| Required security scanner | `npx @Codex-flow/cli@latest security scan` attempted; npm returned 404 because the uppercase package name is invalid/unavailable. This scan did not run or pass |
| Real external local-model response | Not tested; requires user endpoint/model |

## Remaining validation limits

- Browser coverage uses desktop/iPhone/iPad Chromium emulation. Physical iOS hardware and Safari remain untested.
- Real cached Qwen inference and production HTTP/SSE are tested; DGX Spark hardware and independent human teaching quality are not measured. The frozen benchmark keeps unfilled human scores visible.
- The prescribed scanner package is unavailable; successful dependency audits and application tests are recorded separately.
- Coaching is grounded in inspectable board/engine statements and checked wording. It cannot verify arbitrary open-ended chess prose or prove an engine's internal strategic reasoning.
- Opponent levels and learning observations are not calibrated Elo estimates; transfer associations do not prove causal improvement.
- Mobile PWA installation needs HTTPS. Cached shell assets do not provide offline server gameplay or analysis.
