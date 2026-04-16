#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TEST_IMAGE="mediavault-test:latest"

# Determine test target from arguments
MODE="${1:-}"
if [ "$MODE" = "fast" ]; then
    TEST_ARGS="tests/ --ignore=tests/test_performance.py -m 'not slow'"
elif [ -n "$MODE" ]; then
    TEST_ARGS="$MODE"
else
    TEST_ARGS="tests/"
fi

# ---------------------------------------------------------------------------
# Ensure the app container is running (build + start if needed)
# ---------------------------------------------------------------------------
ensure_app_running() {
    if ! docker compose ps --status running 2>/dev/null | grep -q "api"; then
        echo "==> App container not running — starting with docker-compose up -d ..."
        docker-compose up -d --build
        echo "==> Waiting for healthcheck ..."
        local retries=0
        while [ $retries -lt 30 ]; do
            if curl -sf http://localhost:5000/healthz >/dev/null 2>&1; then
                echo "==> App is healthy."
                return 0
            fi
            retries=$((retries + 1))
            sleep 2
        done
        echo "WARNING: healthcheck did not pass within 60 s — continuing anyway." >&2
    else
        echo "==> App container already running."
    fi
}

# ---------------------------------------------------------------------------
# Docker path -- preferred for reproducible CI
# ---------------------------------------------------------------------------
run_docker_tests() {
    # Make sure the main app is up (builds image if needed)
    ensure_app_running

    echo "==> Building test image..."
    docker build -f Dockerfile.test -t "$TEST_IMAGE" .

    echo "==> Running tests inside Docker..."
    # Generate a one-time encryption key for the test run
    ENCRYPTION_KEY=$(python3 -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())" 2>/dev/null \
        || python  -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())" 2>/dev/null \
        || docker run --rm "$TEST_IMAGE" python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())")

    docker run --rm \
        -e DATABASE_URL="sqlite:///:memory:" \
        -e FIELD_ENCRYPTION_KEY="$ENCRYPTION_KEY" \
        "$TEST_IMAGE" \
        python -m pytest $TEST_ARGS --cov=app --cov-fail-under=80 -v --tb=short
}

# ---------------------------------------------------------------------------
# Host path -- fallback when Docker is not available
# ---------------------------------------------------------------------------
run_host_tests() {
    echo "==> Docker not available, falling back to host-based test execution..."

    # Verify Python 3.9+
    PYTHON=$(command -v python3 || command -v python || true)
    if [ -z "$PYTHON" ]; then
        echo "ERROR: Python not found. Please install Python 3.9+" >&2
        exit 1
    fi

    PYTHON_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYTHON_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
    PYTHON_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
        echo "ERROR: Python 3.9+ required. Found: $PYTHON_VERSION" >&2
        exit 1
    fi

    echo "Using Python $PYTHON_VERSION"

    # Create venv if needed
    VENV_DIR=".venv-test"
    if [ ! -d "$VENV_DIR" ]; then
        $PYTHON -m venv "$VENV_DIR"
    fi

    # Detect OS to select correct venv scripts directory
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
        VENV_BIN="$VENV_DIR/Scripts"
    else
        VENV_BIN="$VENV_DIR/bin"
    fi

    # Install deps
    "$VENV_BIN/pip" install --quiet -r requirements.txt
    "$VENV_BIN/pip" install --quiet pytest pytest-flask pytest-cov

    # Set environment
    export DATABASE_URL="sqlite:///:memory:"
    export FIELD_ENCRYPTION_KEY=$($PYTHON -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())")

    # Run tests
    "$VENV_BIN/pytest" $TEST_ARGS --cov=app --cov-fail-under=80 -v --tb=short
}

# ---------------------------------------------------------------------------
# Entrypoint -- try Docker first, fall back to host
# ---------------------------------------------------------------------------
if command -v docker &>/dev/null && docker info &>/dev/null; then
    run_docker_tests
else
    run_host_tests
fi
