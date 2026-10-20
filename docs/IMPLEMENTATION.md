# Implementation and verification record

Updated: 20 October 2026. Final source and verification record. Unchecked environment-dependent checks are not claims of completion. Source implementation, automated verification, and real deployment verification are recorded separately.

## Decisions and dependencies

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
- [ ] Verify real user-supplied model endpoint; none was supplied for this build.

## Verification evidence

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

## Known outstanding work

- Browser tests use Chromium with desktop, iPhone, and iPad viewport/device emulation. Physical iPhones/iPads and Safari were not tested.
- No real Qwen/DGX Spark endpoint was supplied. The actual container-to-container compatible API protocol and failure handling passed, while live model inference quality/compatibility remains unverified.
- The required named security-scanner package could not be installed; dependency audit and application tests are separate evidence and do not replace that scan.
- Coaching uses bounded, verified statement selection, with deterministic fallback. It cannot express arbitrary tactical claims or deeper strategic explanations outside its catalog.
- Difficulty levels are intentionally imperfect practice opponents and are not calibrated to beginner Elo ratings. The curriculum is an initial library; richer topic variety and larger repertoires require additional original or appropriately licensed content.
- PWA installation on mobile requires HTTPS; offline cached assets do not provide offline server gameplay or analysis.
