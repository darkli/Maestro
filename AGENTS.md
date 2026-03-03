# Repository Guidelines

## Project Structure & Module Organization

Core application code lives in `src/maestro/`. Key modules include `cli.py` for the command entrypoint, `orchestrator.py` for task flow, `manager_agent.py` for model decisions, `tool_runner.py` for coding-tool execution, and `telegram_bot.py` for remote control. Tests live in `tests/` and generally mirror the module or behavior under test, for example `tests/test_tool_event.py`. Prompt assets are stored in `prompts/`. Deployment and operations material lives in `deploy.sh`, `deploy/`, and `docs/`. Legacy code is isolated under `_legacy/` and should not receive new feature work.

## Build, Test, and Development Commands

Use Python 3.10+.

- `pip install -e .` installs the package in editable mode.
- `pip install -e .[dev]` installs local development dependencies, including `pytest` and `ruff`.
- `PYTHONPATH=src python -m maestro.cli run "需求"` runs the CLI without installing the console script.
- `pytest tests/ -v` runs the full test suite.
- `pytest tests/test_codex_runner.py -v` runs a focused test file during iteration.
- `ruff check src tests` is the expected lint pass when touching Python code.

## Coding Style & Naming Conventions

Use 4-space indentation and standard Python naming: modules, functions, and variables in `snake_case`; classes in `PascalCase`; constants in `UPPER_SNAKE_CASE`. Keep imports package-qualified with the `maestro.*` prefix where applicable. Follow existing patterns built around `dataclass` configuration models and small, single-purpose functions. User-facing strings, comments, docstrings, and most documentation in this repository are written in Chinese; preserve that convention.

## Testing Guidelines

Tests use `pytest`. Add or update tests for any change to CLI behavior, orchestration logic, configuration loading, prompt handling, or deployment safeguards. Name files `test_<feature>.py` and keep test cases behavior-focused. Prefer fixtures in `tests/conftest.py` or local fixtures over ad hoc setup. Run the narrowest relevant test first, then finish with `pytest tests/ -v`.

## Commit & Pull Request Guidelines

Recent history favors concise, action-oriented commits, often with Conventional Commit prefixes such as `feat(...)`, `fix(...)`, and `docs(...)`, followed by a short Chinese summary. Keep commits scoped to one change. Pull requests should explain the problem, summarize the approach, list validation commands run, and include screenshots or terminal snippets when changing CLI output, Telegram flows, or deployment behavior.

## Configuration & Security Tips

Do not commit real secrets from `config.yaml` or `deploy.env`. Start from `config.example.yaml` and `deploy.env.example`. Treat `prompts/` and deployment scripts as operationally sensitive: changes there should be tested explicitly.
