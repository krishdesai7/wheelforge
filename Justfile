# Justfile

# Run mutable development fixes (modifies code)
# uv run just m[utable]
alias m := mutable
mutable:
    uv sync -U
    uv run pyrefly infer --return-types --parameter-types --imports --containers
    uv check --fix
    uv format
    uv run ruff check --fix --unsafe-fixes
    uv run pytest -q

# Run immutable repository checks (read-only)
# uv run just i[mmutable]
alias i := immutable
immutable:
    uv sync --locked
    uv run --locked pyrefly check --min-severity info
    uv check --locked
    uv format --diff --check
    uv run --locked ruff check --fix
    uv audit --locked
    uv run --locked complexipy --suggest-refactors
    uv run --locked pytest -q