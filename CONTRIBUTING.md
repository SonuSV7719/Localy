# Contributing to Localy

Thanks for your interest in improving Localy! This guide covers how to get set up, our workflow, and the checks we expect before a pull request.

Localy is a local LLM platform made of two parts:

- **Backend** — Python 3.12+ FastAPI service, managed with [`uv`]. Source in `backend/src/localy/`, tests in `backend/tests/`. The API server runs on port `11434`.
- **Desktop app** — Tauri 2 + React + TypeScript. Frontend in `desktop/`, Rust in `desktop/src-tauri/`.

## Development setup

See [`docs/development-guide.md`](docs/development-guide.md) for the full walkthrough. In short:

**Backend**

```bash
cd backend
uv sync              # install dependencies
uv run localy serve  # start the API server on port 11434
```

**Desktop app**

```bash
cd desktop
npm install
npm run tauri dev
```

## Workflow

We never commit directly to `master`. Instead:

1. Create a branch off `master` (e.g. `feat/model-search`, `fix/pool-reconnect`).
2. Make your changes with focused commits.
3. Open a pull request against `master`.
4. Address review feedback, then merge once approved and checks pass.

## Commit messages

We use [Conventional Commits]. Prefix the summary with a type:

- `feat:` — a new feature
- `fix:` — a bug fix
- `docs:` — documentation only
- `refactor:`, `test:`, `chore:`, `perf:`, etc. as appropriate

Example: `fix: reconnect pool workers after transient network drop`

Keep the summary in the imperative mood and under ~72 characters. Add a body when the "why" isn't obvious.

## Checks before opening a PR

Please run the relevant checks locally and make sure they pass.

**Backend**

```bash
cd backend
uv run pytest
```

**Desktop (frontend)**

```bash
cd desktop
npx tsc --noEmit   # type-check
npm run build      # production build
```

**Desktop (Rust)**

```bash
cd desktop/src-tauri
cargo check
```

## Code style

Match the surrounding code. Follow the conventions, naming, and formatting already used in the file you're editing rather than introducing a new style. Keep changes focused — unrelated refactors are best in their own PR.

## Reporting bugs and requesting features

Use the issue templates on GitHub. Bug reports with clear reproduction steps, environment details, and logs are the easiest to act on.

Happy hacking!

[`uv`]: https://docs.astral.sh/uv/
[Conventional Commits]: https://www.conventionalcommits.org/
