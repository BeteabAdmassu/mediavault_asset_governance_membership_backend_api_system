#!/usr/bin/env bash
set -euo pipefail

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

# Determine test target
MODE="${1:-}"
if [ "$MODE" = "fast" ]; then
    TEST_ARGS="tests/ --ignore=tests/test_performance.py -m 'not slow'"
elif [ -n "$MODE" ]; then
    TEST_ARGS="$MODE"
else
    TEST_ARGS="tests/"
fi

# Run tests
"$VENV_BIN/pytest" $TEST_ARGS --cov=app --cov-fail-under=80 -v --tb=short
