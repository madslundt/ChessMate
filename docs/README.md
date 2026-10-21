# Setup and usage guide

This guide covers running and operating Chessmate. For a product overview, start at the repository [README](../README.md). For component boundaries and data flow, see [ARCHITECTURE.md](ARCHITECTURE.md); implementation status, verification, and known limitations are in [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Repository setup

The GitHub repository is [madslundt/ChessMate](https://github.com/madslundt/ChessMate). Use `main` as the initial branch and `https://github.com/madslundt/ChessMate.git` as the `origin` fetch and push URL.

To clone the repository after its first commit has been pushed:

```sh
git clone https://github.com/madslundt/ChessMate.git
cd ChessMate
```

To connect an existing source folder that has no Git metadata, run from that folder:

```sh
git init -b main
git remote add origin https://github.com/madslundt/ChessMate.git
```

If the folder is already a Git repository, skip initialization. If `origin` already exists, update it with `git remote set-url origin https://github.com/madslundt/ChessMate.git` instead of adding it. Verify the configuration with `git remote -v`.

Remote configuration is local Git metadata and is not included in a clone or source archive. Setting `origin` does not commit or push files. The repository's `.gitignore` excludes local environment files, virtual environments, dependencies, databases, and generated test/build output; `config/.env.example` remains available as the configuration template.

## Start with Docker

Requirements: Docker Engine with the Compose plugin, approximately 2 GB free memory, and outbound access during image/dependency installation. No paid account or external chess service is required.

From the repository root:

```sh
./scripts/start.sh
```

The script creates an ignored `config/.env` with a random PostgreSQL password, builds the application, applies database migrations, and waits for service health. Open [http://localhost:8080](http://localhost:8080) and create or select a local profile. Default local profiles keep games and progress separate without passwords. Enable the optional authenticated mode below before allowing untrusted access.

The migration job preserves existing games and preferences. The current schema adds saved coaching evidence/discovery state and calculation events at revision `28e4cdfddcb2`; the public curriculum contains 87 exercises. The generated environment file has mode `0600`. Current verification is recorded in [IMPLEMENTATION.md](IMPLEMENTATION.md).

To configure the environment before starting:

```sh
cp config/.env.example config/.env
chmod 600 config/.env
# Edit config/.env: replace POSTGRES_PASSWORD with a random hexadecimal password.
# Configure your inference server, browser origins, and bind address if needed.
./scripts/start.sh
```

Only the frontend publishes a host port. PostgreSQL and FastAPI are reachable inside the Compose network. Stockfish is installed in the backend image. Containers run as nonroot users; frontend/backend filesystems are read-only, with temporary storage in `/tmp`.

The frontend runtime uses the Nginx 1.30 stable branch, verified against the [official image's supported tags](https://hub.docker.com/_/nginx). Base-image tags allow patch updates; application dependencies are locked separately.

The migration job runs after the database becomes healthy and must succeed before the backend starts. Compose health dependencies follow the [Docker startup-order documentation](https://docs.docker.com/compose/how-tos/startup-order/).

Nginx tracks backend address changes using a shared upstream and Docker's embedded DNS, with a five-second cache lifetime. This uses the open-source [`resolve` parameter supported since Nginx 1.27.3](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#server) and [Docker's embedded resolver](https://docs.docker.com/engine/network/#dns-services). To run the isolated address-change regression check against the production proxy configuration:

```sh
docker pull nginx:1.30-alpine
.venv/bin/python tests/deployment/dns_recovery.py
```

The check creates only temporary `chessmate-dns-check-*` containers and a private network, moves a fixture backend to a different IP, and verifies API/docs/OpenAPI recover without restarting Nginx. It cleans up its resources and does not touch the running Compose application.

## Connect your DGX Spark or another local model server

Set these values in `config/.env`:

```dotenv
LLM_BASE_URL=http://192.168.1.50:8000/v1
LLM_MODEL=your-served-model-name
LLM_API_KEY=
LLM_TIMEOUT=90
LLM_MAX_TOKENS=2000
LLM_TEMPERATURE=0.2
```

Use the exact model identifier served by your inference server. The application does not assume a Qwen variant or require OpenAI. `LLM_BASE_URL` is an API base URL, including `/v1` when your server requires it. A blank API key is supported for local servers without authentication. The endpoint must be reachable from the backend container; `localhost` inside that container means the container itself. For an inference server on the Docker host, use `http://host.docker.internal:PORT/v1`.

Then apply configuration changes:

```sh
docker compose --env-file config/.env -f config/compose.yaml up -d --build --wait
```

LLM credentials stay in backend environment variables. They are not part of the frontend bundle or returned in settings responses. The adapter calls `/v1/chat/completions` with streaming enabled and expects a JSON selection of verified fact identifiers. It adds `/v1` when the configured base URL does not already end with it. When the server is absent, times out, or returns invalid structured output, the coach uses deterministic explanations derived from the analyzed position. Health reports whether inference is configured; it does not guarantee that a remote model is currently reachable.

**Test LLM** in Settings runs a sample position through the same streaming request and evidence validation used by coaching, using the connection currently entered in the form. It displays a verified coaching reply on success and reports an error if the model's response cannot be used. Testing does not save the connection. A successful sample does not guarantee that every later response will pass validation.

An actual container-to-container OpenAI-compatible protocol fixture passed: valid streamed evidence selection produced `local_llm_verified`; malformed JSON, illegal move/variation references, and a timeout produced deterministic fallback. Context checks covered exact FEN, learner color, side to move, legal moves, requested candidate, and legal engine variation. This verifies the adapter protocol, not model inference quality. A cached local Qwen model is also evaluated against the frozen teaching benchmark; see the current verification record for actual provider results. DGX Spark hardware itself has not been tested.

Reasoning models share the output-token budget between thinking and the final JSON. The defaults allow 2,000 tokens and 90 seconds so the model can reason before answering. Existing installations should update `LLM_MAX_TOKENS` and `LLM_TIMEOUT` in `config/.env` if they still use 600 tokens and 35 seconds. Leave `LLM_REASONING_EFFORT` blank to preserve the provider's default reasoning behavior; only set an explicit effort when supported by your provider. Setting it to `none` disables reasoning. Model failures show a specific fallback reason in chat rather than labeling every failure as offline. Game-review questions use the saved pre-move grades available up to the selected position, including without a model.

## LAN, mobile, and HTTPS

For access from an iPhone, iPad, or another computer, set `BIND_ADDRESS` to the server's LAN address, or `0.0.0.0`, and add the full browser URL to `ALLOWED_ORIGINS`:

```dotenv
BIND_ADDRESS=192.168.1.20
PORT=8080
ALLOWED_ORIGINS=http://localhost:8080,http://192.168.1.20:8080
COOKIE_SECURE=false
```

Open `http://192.168.1.20:8080` from the device. Use your own HTTPS reverse proxy or VPN for remote access. With HTTPS, set `COOKIE_SECURE=true` and include the HTTPS origin. Nginx forwards API requests on the same origin, and disables response buffering for streaming coaching. This uses the documented [Nginx proxy buffering behavior](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering).

Service workers and installable PWA behavior require a secure browser context: HTTPS, or localhost during development. On plain LAN HTTP the responsive website still works, but offline installation features may be unavailable. Cached interface assets do not replace the backend: live play, saved data, and analysis require a connection to your server.

## Optional authenticated deployment

Trusted local profiles remain the default. For an installation accessible to untrusted users, provision passwords first, then enable authenticated mode. Existing profile names, games, preferences and histories are retained. Set a password for an existing profile using an interactive terminal:

```sh
docker compose --env-file config/.env -f config/compose.yaml exec backend \
  python scripts/manage_accounts.py "Your profile name"
# For a new account, append --create.
```

The command prompts twice; passwords never enter command arguments. It also revokes old sessions. Add these values to `config/.env` and apply them with `up -d --build --wait`:

```dotenv
SECURE_DEPLOYMENT=true
ALLOW_REGISTRATION=false
COOKIE_SECURE=true
ALLOWED_ORIGINS=https://your-chessmate-host.example
```

Use HTTPS with `COOKIE_SECURE=true`. For loopback HTTP testing only, use `COOKIE_SECURE=false`. `ALLOW_REGISTRATION=false` requires the installation owner to provision accounts; explicitly enable it to offer the Create account form. The first sign-in uses the profile name and password. Settings offers password changes, and Sign out revokes the current session. Lost passwords are reset with the same local administration command. Reverting `SECURE_DEPLOYMENT` to false restores trusted profile selection, so do not do that on an untrusted network.

Authenticated mode uses salted PBKDF2-HMAC-SHA256 with 600,000 iterations, following the [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Only digests of random session tokens are stored; cookies are HttpOnly, SameSite Strict and optionally Secure using [Starlette's cookie controls](https://www.starlette.dev/responses/). Sessions expire after seven days, rotate on sign-in, and are revoked on sign-out/password change. Registration and sign-in are rate limited. The bundled proxy replaces client forwarding headers so they cannot supply a rate-limit address. Keep API/database ports private and protect backups and server-side inference credentials.

## Everyday use

- **Play:** choose a side and computer level, then play; the computer replies automatically by default. Select **Coach first** in Settings when you want to pause for feedback or coaching. Games save automatically.
- **Explore:** test moves on an independent analysis board, undo or reset the variation, and return to the actual game. Committing a variation submits its first move for authoritative server validation.
- **Candidates and hints:** request engine candidates when ready for spoilers, or reveal progressive hints. These use the selected position, including hypothetical positions.
- **Show on board:** feedback, candidates, coaching responses, review, and solved lessons offer supported board demonstrations. Choose a candidate for playback or compare up to three resulting positions at the same continuation step; desktop comparison expands to three boards. Use first/previous/play/pause/next/last and the speed control. **Return to game** immediately restores the saved position. The first two hint levels omit move arrows and variation metadata.
- **Calculate before moving:** play a candidate and predicted replies on a separate board, or enter notation. Check the line and optional final-position assessment; every ply is graded and the first weaker reply is identified. Revise the branch, compare a stronger continuation, or commit only the first candidate through the normal revision check. Progress saves accuracy, hints, retries and independence, and offers replayable calculation history.
- **Retry this position:** a confidently verified game mistake becomes a private exercise. Wrong attempts, hints, assisted solutions and independent solutions enter your learning history. **Return to game** restores the original game; other positions remain available for free exploration.
- **Play pace:** choose automatic replies, coach first, or independent play. Coach first waits for **Let computer move**, giving you time to ask questions. Settings persist this preference along with text/board presentation, automatic/on-request arrows, piece/threat highlights, animation, playback speed and automatic return. Recommended beginner/intermediate/advanced settings can be overridden individually.
- **Full-game analysis:** open a saved or imported game in Analyze and select **Analyze all moves**. Both sides receive assessments in a background job; critical decisions receive the separate 5–20-second deep budget. Progress shows completed moves and critical rechecks. Stop cancels the actual UCI search and discards uncommitted work. If the game changes before completion, the stale result cannot overwrite it. Very long jobs can resume from a committed partial result.
- **Active-recall review:** in Analyze, select an assessed move and write your intended move, the opponent's threat, and your plan before revealing the engine feedback. Notes and reveal state are saved per game position in this browser's local storage.
- **Coach:** ask about the current position. Independent, guided, learning, and Socratic styles control how verified observations and questions are presented. Guided mode can flag an actually exposed piece before a move; learning mode adds phase-specific explanations. Guided/direct controls can change mid-conversation. Socratic discovery remembers noticed pieces, attackers, candidate replies and evaluated outcomes; help becomes more specific when requested. Conversations save their exact position, evidence and visual playback, including after reload. Optional **Hold to talk** and **Læs svar op / Speak reply** controls support browser speech or separately configured OpenAI-compatible STT and TTS providers. Turn reply reading on to have each new coach response read aloud; click again to turn it off. Choose each provider in Settings. A spoken question is added to the coach input for review; the browser path may use the browser's speech service, while server STT sends the recording to the configured endpoint.
- **Learn:** choose a topic, play the requested move, use optional hints, and read the solution explanation. Multi-move lessons accept verified alternatives and give branch-specific hints. Progress combines topic mastery, granular observed skills and calculation accuracy. Later matching live-game decisions are shown as evidence of application after practice, with an explicit association qualification.
- **Opening repertoire:** use Learn to save legal lines for white or black, then generate private practice positions. Only continuations passing a fresh Stockfish comparison become exercises. Saved lines can be listed and deleted in the interface or through the repertoire API.
- **Practice sessions:** choose five-minute daily or ten-minute mixed practice, tactical/opening/endgame sessions, review sessions, past mistakes, or a specific curriculum category. Due reviews and weak topics influence the selection.
- **History and progress:** resume games and revisit mistakes. Progress includes a personalized five-session study plan and a trend of engine-assessed move quality across computer/training games. The trend is a practice signal, not a rating or proof that practice caused improvement. Settings control language, board presentation, feedback, and analysis preferences. The header's **Dark mode / Light mode** switch saves immediately; **System** in Settings follows changes to your device appearance.

## Operations and database backup

Inspect services and logs:

```sh
docker compose --env-file config/.env -f config/compose.yaml ps
docker compose --env-file config/.env -f config/compose.yaml logs --tail=100 backend migrate
curl --fail http://localhost:8080/api/health
```

Interactive OpenAPI documentation is served at [http://localhost:8080/docs](http://localhost:8080/docs). The browser sends the selected profile ID in trusted mode; authenticated mode derives ownership from the session cookie and rejects a conflicting profile header.

Stop containers while keeping data:

```sh
docker compose --env-file config/.env -f config/compose.yaml down
```

The named `chessmate_database` volume persists accounts, games, conversations, and learning progress. Do not pass `down --volumes` unless you intend to erase this database. Back up before upgrading:

```sh
docker compose --env-file config/.env -f config/compose.yaml exec -T db \
  pg_dump -U chessmate -d chessmate > /path/to/private-backup.sql
```

Restore into an empty database with matching schema/version using `psql`, then apply migrations when appropriate. Database backups contain private user data; store them outside the repository. Keep the original database password when restarting an existing volume: changing `POSTGRES_PASSWORD` alone does not change an initialized PostgreSQL user's password.

## Verify the running Docker deployment

These checks use the actual Nginx/React/FastAPI/PostgreSQL/Stockfish stack on port 8080. Install local development dependencies below and the Chromium test browser first. The HTTP and browser checks create disposable local test accounts and data for inspection; existing user data is retained.

```sh
npm exec --prefix src/frontend -- playwright install chromium
E2E_BASE_URL=http://127.0.0.1:8080 npm --prefix src/frontend run test:e2e
DEPLOY_BASE_URL=http://127.0.0.1:8080 node tests/deployment/training-browser.mjs
DEPLOY_BASE_URL=http://127.0.0.1:8080 DEPLOY_DEVICE=mobile node tests/deployment/training-browser.mjs
PWA_BASE_URL=http://127.0.0.1:8080 node tests/e2e/verify-pwa.mjs
```

The original production browser checks covered automatic turns, failure recovery, Explore/history isolation, theme persistence, training and both repertoire colors. The expanded coaching suite also runs against the current production image; current counts and outcomes are recorded in IMPLEMENTATION.md. The profile-scoped PWA check passed: private responses were fetched through the controlling service worker but excluded from every cache, and the public shell reloaded offline.

Verify durable state across a full stack stop/start:

```sh
.venv/bin/python tests/deployment/check_http.py seed --base-url http://127.0.0.1:8080
docker compose --env-file config/.env -f config/compose.yaml stop frontend backend db
docker compose --env-file config/.env -f config/compose.yaml up -d --wait
.venv/bin/python tests/deployment/check_http.py resume --base-url http://127.0.0.1:8080
```

The helper checks exact game revisions/move evidence, PGN/promotion state, preferences, FEN-bound conversations, review and seed identifiers across restart. It uses disposable trusted profiles, stores its temporary state in an ignored mode-`0600` file, and removes both that file and disposable profiles after a successful resume unless `--keep-profiles` is passed.

Run backend tests inside the built production image, with no network, a read-only root filesystem, and a disposable SQLite database in memory-backed `/tmp`:

```sh
docker run --rm --name chessmate-backend-verification --read-only \
  --tmpfs /tmp:rw,size=256m,mode=1777 --network none --cap-drop ALL \
  --security-opt no-new-privileges:true \
  -e DATABASE_URL=sqlite:////tmp/chessmate-tests.db \
  -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" chessmate-backend \
  python -m pytest tests/backend -q -p no:cacheprovider
```

The expanded backend suite passes inside the nonroot Python 3.12/Stockfish 17 image; see the current implementation record for counts. This includes the automatic-reply default, preserved opt-out, analysis cancellation, learning evidence and optional authenticated accounts. To repeat the isolated compatible-provider protocol check without changing the running stack:

```sh
.venv/bin/python tests/deployment/check_llm_protocol.py
```

The protocol fixture uses separate temporary backend/provider containers, validates real HTTP/SSE transport and context, checks failure fallback, and removes its resources. It does not call an actual Qwen model.

Recheck all 87 curriculum entries, including every authored continuation ply, without changing content:

```sh
docker compose --env-file config/.env -f config/compose.yaml exec -T backend \
  python scripts/validate_exercises.py --require-curriculum --seconds 0.3
```

## Local development and checks

Python 3.12+, Node 22.12+, and Stockfish are required. Install Stockfish through your OS package manager, or set `STOCKFISH_PATH` to an executable binary. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r src/backend/requirements.lock
npm --prefix src/frontend ci
DATABASE_URL=sqlite:///./config/chessmate.local.db \
  .venv/bin/uvicorn src.backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
npm --prefix src/frontend run dev
```

Vite proxies `/api` to the local backend. SQLite is a development convenience; Docker deployment uses PostgreSQL and Alembic migrations. Configure production migrations explicitly outside Compose with:

```sh
.venv/bin/alembic -c src/backend/alembic.ini upgrade head
```

`requirements.lock` pins the exact backend dependency versions used for this build; the Dockerfile installs that lock file. `requirements.txt` remains the direct dependency range manifest for intentional future upgrades. Frontend installs use `package-lock.json` through `npm ci`.

Run the validation suite:

```sh
./scripts/check.sh
npm exec --prefix src/frontend -- playwright install chromium
npm --prefix src/frontend run test:e2e
```

`check.sh` runs backend regressions, the frontend production build/unit tests, and the Compose configuration check. Current counts are recorded in IMPLEMENTATION.md. The default browser command expects the backend and Vite development server running. Browser verification covers desktop (1488 × 1058), iPhone 13, and iPad Mini Chromium viewports. These are emulated devices: physical iPhones/iPads and Safari have not been tested. Actual Docker runtime verification is recorded above separately from configuration validation.

To verify the production frontend, keep the backend running, then start Vite preview in a separate terminal after a successful build:

```sh
npm --prefix src/frontend run preview -- --host 127.0.0.1 --port 4173
```

Then run:

```sh
E2E_BASE_URL=http://127.0.0.1:4173 npm --prefix src/frontend run test:e2e
PWA_BASE_URL=http://127.0.0.1:4173 node tests/e2e/verify-pwa.mjs
```

The PWA check verifies first-visit service-worker control, precached JavaScript/CSS, offline shell reload, and exclusion of private API data from the asset cache. The build manifest and asset hash version the shell cache. Production browser scenarios and the offline-shell check pass against the built image; see [IMPLEMENTATION.md](IMPLEMENTATION.md) for verification details.

An additional opt-in integration check creates its own disposable PostgreSQL cluster, runs a full migration round-trip and real application flows, then stops/removes that cluster. It uses a private Unix socket and opens no TCP listener; it never uses an existing database or service:

```sh
.venv/bin/python scripts/check_postgres.py
# If PostgreSQL binaries are not on PATH, specify their directory:
.venv/bin/python scripts/check_postgres.py --bindir /path/to/postgresql/bin
# Homebrew PostgreSQL 17 example:
.venv/bin/python scripts/check_postgres.py --bindir /opt/homebrew/opt/postgresql@17/bin
```

This additional check passed against PostgreSQL 17, including account isolation, transaction conflicts, Stockfish gameplay, training, repertoire practice, and persisted coaching/resume. The same application is also verified through the actual Compose PostgreSQL deployment.

## Exercise content and extension

The seed library contains the original 64 teaching positions plus 20 multi-ply defensive, planning, exchange and endgame lessons, and three additional Stockfish-verified positions on knight outposts, passed pawns and opposition, for 87 total. Solutions include opponent responses, defensive resources, safe simplification, king routes, opposition, rook activity and passed-pawn races. Content includes relative pins, exploiting and breaking pins, defense, activity, outposts, simplification, pawn structure, opposition, drawing positions, rooks on the seventh rank, and opening discipline.

Every seed position and every authored continuation ply is freshly validated with python-chess and Stockfish. The engine compares alternatives against the learning objective instead of blindly rejecting every move outside a single hardcoded solution. The validated import CLI was also run with `--replace`, updating the public seed library.

Inspect the JSON schema in `src/backend/exercise_library.json`. New entries need an identifier, title, category, difficulty, valid FEN, objective, legal solution, objective criterion, explanation, hints, and tags. Preserve the license/attribution of any outside content in `evidence.provenance`. Validate a file locally with:

```sh
.venv/bin/python scripts/validate_exercises.py /path/to/exercises.json --seconds 0.3
.venv/bin/python scripts/validate_exercises.py --require-curriculum --seconds 0.3
```

The first command verifies new content; the second rechecks the included curriculum. A difficult position may need a larger search budget to reach the required minimum depth. To import into a running Docker deployment:

```sh
docker compose --env-file config/.env -f config/compose.yaml cp /path/to/exercises.json backend:/tmp/exercises.json
docker compose --env-file config/.env -f config/compose.yaml exec backend \
  python scripts/import_exercises.py /tmp/exercises.json
```

Imports perform fresh validation before committing and skip existing identifiers. Add `--replace` only when intentionally updating existing public entries; private game-derived exercises cannot be overwritten. On the host, the same import script uses `DATABASE_URL` to select the target database.

## API guide

Profile-scoped data endpoints use the selected profile ID in trusted mode or an authenticated cookie in secure mode. Mutating requests use JSON and browser-origin validation. Core profile, game, analysis, exercise, progress, and settings responses use typed Pydantic models in `src/backend/views.py`. Full request/response schemas are validated and published in `/docs` and `/openapi.json`.

| Purpose | Endpoints |
| --- | --- |
| Profiles | `GET /api/profiles`, `POST /api/profiles`, `PATCH /api/profiles/{id}`, `DELETE /api/profiles/{id}` |
| Account security | `GET /api/profiles/access`, `POST /api/profiles/session`, `DELETE /api/profiles/session`, `PATCH /api/profiles/password` |
| Games | `POST /api/games`, `GET /api/games`, `GET /api/games/{id}` |
| Game commands | `POST /api/games/{id}/moves`, `/computer`, `/undo`; commands include the current revision |
| Export and review | `GET /api/games/{id}/pgn`, `GET /api/games/{id}/review`, `GET /api/games/{id}/conversation` |
| Analysis and coaching | `POST /api/analysis`, `POST /api/hint`, `POST /api/coach` (SSE) |
| Calculation and history | `POST /api/calculation`, `GET /api/calculation/attempts`, `GET /api/calculation/attempts/{id}` |
| Background analysis | `POST /api/analysis/jobs`, `POST /api/games/{id}/analysis-jobs`; poll/cancel with `GET` / `DELETE /api/analysis/jobs/{id}` |
| Batch compatibility | `POST /api/games/{id}/analyze` (revision, start_ply, limit) |
| Exercises | `GET /api/exercises`, `GET /api/exercises/{id}`, `POST /api/exercises/{id}/attempt`, `/hint` |
| Personal learning | `POST /api/training/sessions`, `GET /api/progress`, `POST /api/games/{id}/exercises` |
| Tracked retry | `POST /api/games/{id}/retry` with zero-based `ply`; returns a reverified private exercise |
| Opening repertoire | `GET /api/repertoire`, `POST /api/repertoire`, `DELETE /api/repertoire/{id}`, `POST /api/repertoire/{id}/practice` |
| Preferences and health | `GET /api/settings`, `PATCH /api/settings`, `GET /api/health` |

For example, create a white repertoire with a JSON body such as `{"name":"Italian","color":"white","moves":["e4","e5","Nf3","Nc6","Bc4"]}`. SAN or UCI moves are accepted and normalized to UCI. A custom valid starting `fen` is optional. The practice endpoint returns a training session of verified positions for the selected color.

## Architecture and correctness boundaries

```text
Browser: React / TypeScript / chess.js / react-chessboard
    | same-origin HTTP and streamed coaching
Nginx: static PWA assets + /api reverse proxy
    |
FastAPI: profile selection / game commands / training / coaching
    |                     |                         |
PostgreSQL           Stockfish over UCI     External local LLM
SQLAlchemy/Alembic    python-chess rules     OpenAI-compatible API
```

The browser provides interaction and immediate move previews. The backend owns saved game state, legal move validation, profile scoping, and revision checks. Stored move sequences reconstruct board history; append-only game events preserve the actions behind state changes, including undo. Concurrent updates must match the current revision instead of silently overwriting another move.

The engine service serializes quick Stockfish searches and creates a separate serialized worker for explicit deep analysis. Quick searches are bounded to three seconds; deep searches use five to twenty seconds. Background jobs use one worker, a four-job queue and at most two active jobs per profile; cancellation sends UCI stop, and stale results are ignored. Each worker has a 256-entry, ten-minute cache keyed by full FEN, move stack, time/depth limits, candidate count, and root-move restriction. API analysis evidence is also persisted in PostgreSQL. Candidate moves and principal variations come from Stockfish, with SAN produced by replaying legal moves through python-chess. Game and exploration analysis have explicit position identities so feedback for one position cannot silently become feedback for another.

PostgreSQL stores profiles/preferences, optional authenticated sessions, games/events, coaching messages with exact evidence, discovery state, calculation events, position evidence, exercises/attempts, training sessions, and progress. Profile IDs are selectable local labels in trusted mode; secure mode requires the owning session.

## Evaluation and coaching logic

Stockfish provides evidence; the LLM chooses which verified explanation statements to present. The implementation uses the [python-chess engine API](https://python-chess.readthedocs.io/en/latest/engine.html), including root move restrictions and MultiPV analysis. Candidate `cp` and `mate` values refer to the root side to move; `white_cp` and `white_mate` are provided separately for White-oriented display. Centipawn and mate scores remain separate; a bounded numeric representation is used only for comparisons.

Move grading compares the chosen move with alternatives from the position before that move, under the same time/depth limits and root perspective. It does not use the opponent's next actual move to judge the player's earlier decision. Below depth eight the result is `Uncertain`; the only legal move is `Forced`. Otherwise centipawn losses up to 15, 45, 100, and 220 separate near-best, good, inaccuracy, and mistake decisions, with larger losses normally labeled blunders. Exact best moves and nearly equivalent alternatives receive distinct `Best`/`Excellent` labels. Retaining a forced mate is treated separately from losing one, and an outcome-probability heuristic reduces harsh labels in already decisive positions. Significant mistakes receive a larger same-root recheck; conflicting searches report uncertainty. The interface displays the confidence label. These thresholds are educational estimates, not rating measurements or calibrated win probabilities. Same-budget searches can still disagree; the service avoids grading the identical best move as a blunder because of search noise.

Deterministic observations include legal checks and captures, attacked/defended pieces, material, pins, and candidate continuations. A geometric motif alone is insufficient proof that a tactic wins. Exercises combine an objective predicate with engine evidence so an equally useful alternative can be accepted. The curriculum is authored locally, with validation evidence recorded alongside its content; no external puzzle database is required.

The coaching context identifies the exact FEN, side to move, player, recent history, phase, skill preference, engine candidates, verified observations, and coaching settings. Named candidate moves in a question can receive a separate root-restricted analysis. Historical questions exclude future actual moves, while exploration is explicitly marked hypothetical.

The learner's color remains fixed when the opponent is to move, including while a computer reply is paused. Checks, castling, material, candidate suggestions, and hints distinguish the learner's pieces from the current mover; bilingual regressions cover this boundary.

The model receives dynamically derived explanation statements and composes evidence-reference `segments`, optional `fact_ids`, a candidate UCI move, a verified PV prefix, and a tone. Segments order evidence, use supported teaching framing and may paraphrase through checked equivalent wording. Unsupported paraphrases or redundant raw prose accompanying valid segments are discarded and identified as corrected grounding; only validated evidence is displayed. Unknown identifiers, illegal or unverified moves, unrelated continuations, and spoiler violations are rejected. A standalone legacy `response` field is accepted only when its text exactly matches cited verified statements. Arbitrary prose is never treated as verified merely because it cites valid facts. This closes the free-form verification bypass. It also means unrestricted conversational reasoning remains outside the verified evidence vocabulary; factual safety is not evidence of teaching breadth.

The adapter reads the model's SSE deltas into a bounded buffer, parses and validates the complete selection, and then emits validated text chunks to the browser. Separate analysis and explanation progress states stream immediately; generated wording is held until validation rather than showing unchecked raw model tokens. At most two inference selections run concurrently, with a total deadline, short history, output-size bound, and configurable token limit. Deterministic teaching uses the same evidence when inference fails. General strategic principles remain suggestions, and legal attacks or captures are described without automatically claiming they win material. Mate and stalemate outcomes take priority over material counts. See the [coaching benchmark](COACHING_BENCHMARK.md) for reproducible three-level capture and review instructions.

## Scope and limitations

This application is for local computer games, analysis, and learning. Optional browser or configured-server speech controls support voice coaching during practice. Server speech uses the endpoint, model, optional API key, and TLS setting in Settings; recordings and coach reply text are sent to the configured provider for STT/TTS respectively. Competitive online chess assistance and physical-board support are outside the current scope.

Computer levels permit legal imperfections; their labels are not a calibrated rating estimate. The 87-position curriculum and deterministic strategic indicators are bounded teaching tools rather than comprehensive chess knowledge. Strategy separates geometric observations from qualified plans; model prose stays inside a verified evidence boundary. The move-quality trend is a practice signal, not proof of causal improvement. Real local Qwen evaluation and automated tests do not establish human teaching-quality acceptance or longitudinal improvement. Physical Apple devices/Safari remain untested. Review the up-to-date test evidence in [IMPLEMENTATION.md](IMPLEMENTATION.md).
