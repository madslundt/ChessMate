# Personalized coaching implementation record

Updated: 22 October 2026.

This record tracks the adaptive coaching enhancement separately from earlier coaching work. Passing software checks does not establish that a player learns more effectively; that requires longitudinal user evaluation.

## Repository audit

The existing application already supplies legal full-game play, a five-level Stockfish opponent, engine grading, deterministic bilingual coaching, saved conversations, progressive hints, visual variations, exercises, calculation practice, review, learning events and authenticated profile isolation. Existing full-game analysis runs on request through a bounded in-process queue and saves revision-checked assessments. Existing progress projections combine practice and game evidence but do not provide a complete automatic post-game lifecycle, daily diary or date-range reports.

The enhancement extends those boundaries. It does not require a paid database, new inference provider, Redis or Celery. Game commands remain authoritative; positions and analysis are verified with python-chess and Stockfish.

## Delivery phases and acceptance checks

| Phase | Acceptance criteria | Verification boundary |
| --- | --- | --- |
| 1. Audit and architecture | Reuse existing game, engine, learning and authentication boundaries; preserve data | Existing backend baseline; schema review |
| 2. Assistance evidence | Distinguish general, piece, destination, solution and exploration; historical omissions remain unknown | Assistance API, ownership, move association and undo tests |
| 3. Automatic learning | Finished games queue durable work; retries and restart recovery are idempotent; repeated evidence supports qualified conclusions | Worker lifecycle, evidence uniqueness and profile tests |
| 4. Adaptive opponent | Adaptive default; manual choice preserved; bounded changes require multiple games | Baseline, strong/weak outlier, assistance and manual override tests |
| 5. Realistic training | Continue legally from game positions; blind mode conceals the topic; training evidence stays distinct | Position legality, continuation, selection and assistance tests |
| 6. Diary and calendar | One owned diary per active local date; partial analysis is visible; calendar is navigable | Date/timezone, generation, concurrency, browser and ownership tests |
| 7. Reports | Explicit date-range generation only; counts use structured evidence; saved reports reopen and show staleness | Range, deduplication, empty data, report ownership and browser tests |
| 8. Integration | Existing flows remain functional; migrations preserve data; documented actual verification | Backend regression, frontend build/unit/browser checks and measurements |

Focused backend regressions are in `test_adaptive_integration.py`, `test_adaptive_learning.py`, `test_automatic_lifecycle.py`, `test_diary_lifecycle.py` and `test_gameplay_training.py`. Frontend regressions include `Diary.test.tsx`, `diaryCalendar.test.ts` and `assistance.test.ts`; `tests/e2e/adaptive-learning.spec.ts` exercises the connected browser lifecycle across the three configured viewports. Existing coaching, engine, profile, training, visual and game regressions remain part of the full suites.

## Evidence and interpretation

Verified chess facts include legal moves, FENs, engine scores and inspected variations. Learning observations are statistical interpretations of those facts and include sample size and assistance coverage. A missing mistake is not evidence of mastery when no relevant opportunity was observed. When a known weakness has no relevant opportunities in the recent 120-game window, the profile retains its previous status as historical context and marks current evidence insufficient instead of silently treating the weakness as resolved. A single game cannot establish a recurring weakness or lasting strength.

Assisted success has learning value while remaining distinct from independent performance. Unknown historical assistance must never become independent success simply because no old hint record exists. Repeated success on the same position is less informative than later independent success in an unfamiliar full-game position. Neither association demonstrates causation.

Optional model-generated wording must remain constrained by verified evidence. Deterministic coaching and narratives must remain usable when inference is unavailable. Inference credentials and external-provider settings retain their existing server-side ownership boundaries.

## Verification log

The pre-change baseline on 22 October 2026 passed **318 backend tests in 42.88 seconds**, using the local Python 3.14 virtual environment and Stockfish. There were 22 existing deprecation warnings. This result predates the adaptive changes and is not a final regression claim.

Implementation checks and final measurements are recorded below as they are executed. Environment-dependent checks remain incomplete until explicitly reported as passed.

## Everyday use

1. Choose **New game**. **Adaptive difficulty** is selected initially; Chessmate starts at an accessible internal level while evidence accumulates. Select **Manual difficulty** to choose a fixed level. The active opponent level is shown above the board.
2. Play normally. Use the existing coaching conversation, progressive hints, candidate comparison and board demonstrations when useful. Those disclosures remain valuable learning events and are distinguished from independent decisions.
3. When a game ends, analysis is queued automatically. You can also choose **Resign** after playing a move; the saved result retains its provenance. Completed imported PGNs retain a declared result even when the final board is not checkmate or a draw. The diary shows whether analysis is waiting, incomplete, failed or complete. Manual whole-game and deep analysis remain available in Analyze.
4. Open **Progress** for your learning profile, supporting positions, assistance coverage and priority concepts. Small samples are qualified; a single win or loss does not establish strength or change difficulty.
5. Open **Learn → Play from a real position**. Choose personalized or mixed training, a supported focus, and blind or focused mode. **Continue this position** starts a normal game. You can keep playing after a missed idea.
6. Open **Diary**, select a month and an active date, then read the daily reflection. Game counts distinguish activity; inactive dates do not create empty entries. Month controls also navigate across years. Active days support keyboard arrows, Home/End and Enter, as well as touch.
7. Follow a highlighted decision to Analyze at its original board position, or open a referenced game. Independent, assisted and unknown decisions are displayed separately.
8. Choose a report preset or fill **From** and **To**, then **Generate report**. Reports are saved and can be reopened under **Saved reports**. **Update report** regenerates a stale snapshot. Only daily entries are automatic.

In **Settings**, control automatic completed-game analysis, automatic diary narratives, the diary timezone and difficulty mode. Disabling automatic narrative writing retains structured analysis and calendar data. An explicit diary update can still produce a narrative. Existing coaching language and interface language settings support English and Danish.

## Persistence, backfill and rebuilding

The new database structures are additive: per-game durable analysis state, per-user learning snapshots, daily diary projections and saved report snapshots. Existing append-only learning events carry assistance and game observations. New game columns record completion time, difficulty mode, evidence source, reliable-assistance coverage, optional training context, and declared game results with their completion reason. Existing games retain their moves, history and unknown assistance classification. Migration `c1ad7e201001` adds durable analysis, learning snapshots and game metadata; `c1ad7e201002` adds diaries and reports; `c1ad7e201003` adds declared results and completion reasons. PostgreSQL installations apply Alembic migrations before starting the application. SQLite development startup adds the compatible game columns automatically.

Historical processing is explicitly available through the authenticated `POST /api/learning/backfill` API. Send `{ "limit": 50 }`, follow the returned `next_cursor` using `after_id`, and repeat until it is null. The maximum page is 100. `{ "rebuild": true }` also queues existing projections for recomputation. Existing game evidence is retained. The server estimates historical completion time from available move events, falling back to creation time; it cannot recover an absent original timestamp.

Automatic work retains status, attempts, backoff and lease state in the database. It survives application restarts. Failed work can be retried through backfill. Diary updates rebuild projections from eligible owned games; saved reports retain their original snapshot until explicitly regenerated. Requests for another profile's report or game return no private record.

## Known limits and interpretation

- Opponent levels are internal strength controls, not an Elo estimate. Statistical observations describe demonstrated opportunities, not the player's private thought process.
- Training difficulty is a transparent heuristic based on unfamiliar independent training successes, repetition and available position complexity. It is not an externally validated difficulty calibration.
- Supported concept detection is conservative. Not every strategic error has a verifiable explanation, and absence of an observed error does not establish mastery. Focused training can be unavailable until a suitable verified realistic position exists.
- Repeated familiar positions, assisted training and imported decisions do not establish independent transfer in normal games. Game, training and imported sources remain separate in diary/report statistics and comparative evidence. Forced replies do not count as independently chosen successes. User learning effectiveness requires longitudinal evaluation beyond automated checks.
- Diary/report narratives use a deterministic evidence-grounded synthesis. They remain functional without an LLM and do not provide unrestricted generated prose.
- Historical records without assistance or completion metadata cannot reconstruct missing facts. Backfill preserves that uncertainty.
- Browser checks use Chromium desktop/tablet/mobile emulation. Physical touch devices and Safari require separate verification. The history-size benchmark uses isolated local SQLite and precomputed analysis; the separate engine measurement uses actual Stockfish. Neither establishes production PostgreSQL throughput or multi-user engine capacity.

## Recorded performance measurements

Executed `scripts/benchmark_learning.py --sizes 100 1000 10000 --repeats 3` with local Python 3.14 and isolated temporary SQLite databases. The corpus contains legal four-ply completed games with two precomputed player observations per game, three games per date, and up to 3,334 diary dates. Timings include the in-process HTTP/API path. Peak memory is Python allocations for one request measured separately using `tracemalloc`; it does not include the whole process or Stockfish. The raw results are retained in [the benchmark capture](benchmarks/adaptive-learning-2026-10-22.json).

| Read/action | 100 games median | 1,000 games median | 10,000 games median | Queries at 10,000 | Peak Python memory at 10,000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Learning profile | 3.61 ms | 4.18 ms | 3.00 ms | 2 | 0.09 MiB |
| Existing progress dashboard | 10.36 ms | 15.03 ms | 22.05 ms | 10 | 0.76 MiB |
| One calendar month | 4.14 ms | 5.25 ms | 4.38 ms | 3 | 0.32 MiB |
| One daily diary | 5.26 ms | 6.17 ms | 4.90 ms | 8 | 0.15 MiB |
| Generate 30-day report | 14.48 ms | 14.36 ms | 13.17 ms | 9 | 0.74 MiB |

Four simultaneous learning-profile reads took 11.08 ms in total at 10,000 games. All observed maxima met local targets of 250 ms for profile/calendar, 500 ms for a day, 1 second for the progress dashboard and 2 seconds for a 30-day report. These are local acceptance targets rather than guarantees for another host.

An initial measurement before bounding the old dashboard game-history projection used 50.69 MiB and a 500.75 ms median at 10,000 games. The bounded projection now uses recent history while retaining aggregate game counts; the final capture above measures that implementation. This experiment does not measure PostgreSQL query plans, analysis throughput, interactive engine latency under background load, or distinct simultaneous users. Those deployment measurements remain separate acceptance work.

## Interactive engine and background work measurement

The separate `scripts/benchmark_learning_engine.py` check measured actual Stockfish searches while the durable worker analyzed a four-ply completed game. Six baseline interactive requests had a 108.79 ms median and 268.01 ms maximum; six requests made during background analysis had a 371.04 ms median and 377.15 ms maximum. The background job completed in 8.086 seconds, approximately 0.495 analyzed plies per second, on one attempt and produced two player observations. See [the engine capture](benchmarks/adaptive-engine-2026-10-22.json).

Baseline and concurrent requests used different positions. This is a small host-specific smoke measurement, not a controlled comparative throughput claim, a calibrated latency guarantee or a multi-user production load test. It confirms that interactive requests completed during actual background processing.

## Integration findings corrected during validation

Restart testing reproduced and fixed SQLite lease recovery comparing naive database timestamps with aware Python timestamps. Real PostgreSQL simultaneous completions reproduced a diary-serialization deadlock; the final lock mode preserves per-user serialization while allowing game foreign-key checks. Concurrent automatic and manual analysis of a completed imported game also exposed a two-second deep-engine lock timeout. Deep work now waits within a cancellable bound, and manual review waits for and reuses the automatic assessments. A changed revision is accepted only when stored events positively prove analysis-only changes; undo/redo or real game changes still reject stale work. Saved report fingerprints now detect a newly completed game before a diary rebuild, and timezone changes cannot count an earlier local-day projection twice.

Browser validation also reproduced a transient board-explanation hover changing document height by 48 pixels and repeatedly moving the page scroll position. Transient explanations now overlay the board area while pinned explanations retain normal layout, and the unchanged hover regression passes. Older browser fixtures were brought into line with existing speech settings and active-recall review: learners write an intended move and reveal feedback before checking the engine explanation.

## Final software verification

| Check | Executed result |
| --- | --- |
| Backend regression | 378 tests passed in 62.10 seconds on local Python 3.14/Stockfish; existing deprecation warnings remain |
| Production backend image | Current `config/Dockerfile.backend` built as the isolated validation tag; all 378 tests passed in 73.08 seconds on Python 3.12 with real Stockfish. Read-only root filesystem, dropped capabilities, no network, temporary `/tmp` and read-only test/script mounts; IANA `Europe/Copenhagen` runtime data verified. One existing Starlette warning remains |
| Frontend unit tests, production build and lint | 62 tests passed; build and lint passed |
| PostgreSQL migrations and compatibility | Fresh upgrade/check/downgrade-base/upgrade/check passed with no drift through `c1ad7e201003`; an incrementally upgraded previous-schema database preserved seeded legacy moves, difficulty, revision and unknown assistance |
| PostgreSQL adaptive integration | Real Stockfish, simultaneous game completions, one daily entry, source ownership, reports/staleness, declared nonterminal PGN results and resignation passed |
| New adaptive browser flows | 18 cases passed across desktop, tablet and mobile: adaptive/manual selection, complete-game learning/diary/report lifecycle, blind training, first unsaved assistance, Danish historical calendar and empty reports, resignation and declared PGN results with visible source partitions |
| Optional secure deployment browser flow | Three cases passed across desktop, tablet and mobile against a separate temporary server: registration, sign-in, reload, cookie attributes, profile-header isolation, password change, revoked old credentials and logout |
| Full browser regression | All 231 cases passed in 7.5 minutes across desktop, tablet and mobile, including the separate secure deployment cases; no skipped cases |
| Exact-source contention recheck | After the final checkpoint fingerprint guard, a fresh database and cold Stockfish process passed cancellation/resume/critical-decision review in all three viewports: three cases in 13.4 seconds, with automatic learning enabled |
| History size/read and actual background engine measurements | Captured above and in the two benchmark JSON files |
| Production PWA | Existing `verify-pwa.mjs` passed against the latest production build served by isolated Vite preview: first-visit worker control, JS/CSS precaching, private profile API exclusion and offline shell reload |
| Frontend dependency audit | `npm audit --audit-level=high` on 22 October 2026 reported zero known vulnerabilities; this is separate from the required scanner |
| Required security scanner | Attempted `npx @Codex-flow/cli@latest security scan` on 22 October 2026; npm returned E404 for the unavailable/invalid uppercase package name. The scanner did not run or pass |

Browser checks use the native Vite/FastAPI development stack with isolated temporary SQLite databases and Chromium viewport/touch emulation. Mocked review regressions additionally verify that first-level hints discard move-bearing visual metadata, active recall precedes engine feedback, and previewing cannot mutate the saved game. The model-catalog/TLS fixtures use `E2E_MODEL_HOST=127.0.0.1` for the native backend; Docker runs may use the existing `host.docker.internal` default. The optional secure tests use their own `E2E_SECURE_BASE_URL` and database.

These checks verify software behavior and evidence integrity. They do not prove educational effectiveness, calibrated opponent strength, physical-device behavior or production load capacity.
