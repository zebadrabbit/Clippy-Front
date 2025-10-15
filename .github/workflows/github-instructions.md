<!--
This file is read by GitHub Copilot Chat/Workspace (and some VS Code flows).
Think of it as a repo-wide "behavior contract" for how AI should propose code,
commands, commits, and reviews. Make rules short, explicit, and testable.

House style: concise rules up top; details and examples later. Copilot follows
the rules best when they’re imperative ("Do X, never do Y").
-->

# Copilot Repo Instructions (Python, large project)

<!-- =========================
     CORE INTENT
========================= -->
## Goals
- Build a **reliable, tested, type-checked** Python codebase.
- Keep automation **safe by default**: local commits, manual push, PR review.
- Prefer **clarity over cleverness**. If in doubt, write the simple version.

<!-- =========================
     ENVIRONMENT & EXECUTION
     Teaching Copilot how to run commands safely.
========================= -->
## Environment & Execution Rules
- Always assume a Python virtual environment exists at project root: `.venv/`.
- Before any command that uses Python, pip, pytest, or tooling:
  - Linux/macOS: `source .venv/bin/activate`
  - Windows PowerShell: `.\\.venv\\Scripts\\Activate.ps1`
- Never suggest global installs or `sudo pip`. Use `python -m pip` consistently.
- Respect `pyproject.toml` and `requirements*.txt` as sources of truth.
- If dependencies change, propose:
  1) update the file(s), 2) show the exact install command, 3) note any locks.

<!-- Optional: if you use Poetry/UV/Hatch, replace the above with those workflows. -->

<!-- =========================
     TOOLING & QUALITY GATES
========================= -->
## Tooling (assume VS Code terminal)
- Formatting: **Black** (`black .`)
- Imports: **isort** (`isort .`) aligned with Black profile.
- Linting: **Ruff** (`ruff check .`) with fix when safe (`--fix`).
- Types: **mypy** (or **pyright**) with strictness appropriate to module.
- Tests: **pytest** with `-q` by default; allow `-k` for targeted runs.
- Docs: **MkDocs** or **Sphinx** (whichever this repo uses).
- When proposing commands, include them **in the correct order**:
  1) activate venv → 2) install → 3) lint/format → 4) type-check → 5) test.

<!-- =========================
     GIT WORKFLOW & PUSH POLICY
========================= -->
## Git Workflow
- Work on feature branches only. Never commit directly to `main`.
- Branch names: `feature/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`.
- **Never push automatically.** When asked to “publish,” open a PR from the feature branch.

## Commit Policy
- Prefer **small, logical commits** that pass lint + tests locally.
- Use **Conventional Commits**: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `perf:`, `build:`, `ci:`.
- Generate messages with:
  - **Subject**: imperative, ≤72 chars.
  - **Body**: “why” before “what”; bullet the notable changes.
  - **Footer**: issues/PR refs, breaking-change notes.
- If a change is tiny (e.g., single typo), suggest batching unless urgent.

## Guardrails (hard “no”)
- Do not suggest `git push` or background sync. Add “Manual push required.” to any Git step list.
- Do not edit CI secrets or propose commands that expose credentials.
- Do not alter `main` protection rules.

<!-- =========================
     CODE STYLE & ARCHITECTURE
========================= -->
## Code Style
- Write explicit, readable code. Avoid “magic.”
- Always add/maintain type hints in public APIs. Prefer `typing` over runtime checks when feasible.
- Keep functions short; extract helpers when exceeding ~40 lines or 5 params.
- Logging > print. Use structured logs where the stack uses it.
- Public APIs must have docstrings (Google or NumPy style; be consistent).

## Architecture Boundaries
- Keep layers separate:
  - `domain/` (pure logic), `adapters/` (I/O: db, http, filesystem), `app/` (use-cases/services), `cli/` or `api/` (interfaces).
- No cross-layer imports that break the direction: **interfaces depend inward; infrastructure depends outward**.
- If a change leaks through layers, propose an interface change instead of a shortcut import.

<!-- =========================
     TESTING POLICY
========================= -->
## Testing
- New code requires tests. Aim for meaningful coverage, not number-chasing.
- Unit tests live beside code or under `tests/unit/`; integration under `tests/integration/`.
- Use factories/builders over hand-rolled fixtures where it reduces noise.
- For external calls, **mock boundaries** (HTTP/DB). Prefer contract tests for critical adapters.
- When fixing a bug, add a regression test first.

<!-- =========================
     PERFORMANCE & DATA
========================= -->
## Performance & Data
- Prefer algorithmic clarity; micro-optimizations need a benchmark.
- For datasets/artifacts, never commit large binaries. Use configured storage (e.g., DVC, LFS) and document retrieval steps.

<!-- =========================
     SECURITY & SECRETS
========================= -->
## Security
- Never print or log secrets, tokens, or PII.
- Use `.env` files + example templates; reference them, don’t commit them.
- For crypto and auth flows, prefer well-reviewed libraries and patterns; avoid from-scratch designs.

<!-- =========================
     DOCS & DEVELOPER EXPERIENCE
========================= -->
## Documentation
- If you add a user-facing feature, update docs in the same PR.
- Include runnable snippets with venv activation.
- Keep `README.md` focused on quickstart; move details to `/docs`.

## Developer Experience
- Provide `make`/`just` targets or `tasks.py` (Invoke) for common flows:
  - `setup`, `lint`, `format`, `typecheck`, `test`, `test-watch`, `serve-docs`.
- Copilot should surface these tasks before shelling out long command lists.

<!-- =========================
     PRS & REVIEWS
========================= -->
## Pull Requests
- One coherent topic per PR; avoid kitchen-sink diffs.
- Include summary, risk notes, test evidence (commands + output snippet).
- Copilot review comments should be **actionable** and reference our rules here.
- If tests are added/changed, note *why* and *what behavior* they encode.

<!-- =========================
     MONOREPO / MULTI-PACKAGE (if applicable)
========================= -->
## Multi-Package Guidance
- For `packages/*`, keep independent `pyproject.toml` files with shared tooling config via `ruff.toml`/`mypy.ini` at repo root.
- Cross-package imports go through published interfaces, not relative file spelunking.

<!-- =========================
     INTERACTION PATTERNS FOR COPILOT
========================= -->
## How to Propose Changes (for Copilot)
- When asked to modify code:
  1) Show a **minimal diff**.
  2) Provide a **reasoning note** (1–3 lines).
  3) Include **test changes** if behavior changes.
  4) Provide the **exact command sequence** (activate venv → lint/format → type-check → test).
- When asked to “run” something, first restate any **prereqs** (env vars, services).
- If policy conflicts with a user request, remind them of the rule and propose the compliant path.

<!-- =========================
     EXAMPLES
========================= -->
## Examples

### Example: Safe install & test
```bash
# POSIX
source .venv/bin/activate
python -m pip install -U -r requirements-dev.txt
ruff check . --fix
black .
isort .
mypy .
pytest -q
