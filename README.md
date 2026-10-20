# Chessmate

Chessmate is a self-hosted chess training app for playing, studying positions, and building a regular practice habit. It combines a chessboard and computer opponent with engine-backed analysis, guided coaching, exercises, opening repertoire practice, and progress tracking. Your games and learning history stay on your own installation.

## How it works

1. **Play or choose a lesson.** Start a game against the computer, open an exercise, or pick a topic or practice session.
2. **Explore a position.** Try moves on a separate analysis board, request candidate moves, or reveal hints. Exploring does not change the saved game unless you commit a move.
3. **Review and learn.** Chessmate checks positions and moves with Stockfish, then uses those results for feedback, exercises, and progress recommendations. An optional local, OpenAI-compatible model can help phrase coaching from verified observations; without it, deterministic coaching still works.
4. **Return to your progress.** Games, practice attempts, preferences, and coaching conversations are saved in the installation's database and can be revisited later.

Visual coaching is a core part of the learning flow. Show supported ideas on the board, step through or play a legal variation, compare candidates, and return to the saved game. Coach-first play leaves time for questions, and calculation practice checks predicted replies before you commit a move.

Guided discovery and visual conversations persist across visits. Practice includes 84 verified lessons, adaptive topic recommendations, calculation history, and evidence of later application in games. Deep position and full-game analysis run as cancellable background jobs. Trusted local profiles remain the default; an optional password and session mode supports deployments with untrusted users.

## Get started

The quickest way to run Chessmate is with Docker Compose. You need Docker Engine with the Compose plugin:

```sh
./scripts/start.sh
```

Then open [http://localhost:8080](http://localhost:8080) and create or select a local profile. The setup guide covers configuration, LAN access, backups, local development, and troubleshooting.

## Technology at a glance

The browser interface is built with React. A Python and FastAPI server manages games, training, and saved data; `python-chess` enforces chess rules, and Stockfish analyzes positions and plays the computer opponent. PostgreSQL stores data in the Docker setup. The optional language model runs on an endpoint you configure, and is not required for play or deterministic coaching.

## Documentation

- [Setup, configuration, and everyday use](docs/README.md)
- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Implementation status, verification, and known limitations](docs/IMPLEMENTATION.md)
- [Coaching quality benchmark: 40 positions at three teaching levels](docs/COACHING_BENCHMARK.md)

