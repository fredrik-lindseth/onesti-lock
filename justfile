# Test targets. Requires `just` (https://github.com/casey/just) and uv.

set shell := ["bash", "-uc"]

default:
    @just --list

# Real Home Assistant. target=minimum is the version hacs.json promises,
# target=current the newest release pinned in pyproject.toml. Both must be
# green. Each target has its own venv, and neither touches tests/, which
# runs without Home Assistant installed.
test-ha target="current" *args:
    #!/usr/bin/env bash
    set -euo pipefail
    # `just test-ha target=minimum` passes the whole string positionally,
    # so strip the prefix rather than reject the documented spelling.
    target="{{target}}"; target="${target#target=}"
    case "$target" in
        minimum) python=3.13 ;;
        current) python=3.14 ;;
        *) echo "Unknown target '$target'. Use minimum or current." >&2; exit 2 ;;
    esac
    UV_PROJECT_ENVIRONMENT=".venv-ha-$target" uv run --frozen --python "$python" \
        --group "ha-$target" pytest tests_ha -o asyncio_default_fixture_loop_scope=function {{args}}
