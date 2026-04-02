import json
import pytest
from unittest.mock import patch
from sqlalchemy import text

EXPECTED_TABLES = [
    "users", "roles", "user_roles", "sessions", "login_attempts",
    "risk_events", "blacklists",
    "memberships", "membership_tiers", "ledgers",
    "campaigns", "coupons", "coupon_redemptions",
    "assets", "taxonomies", "dictionaries", "download_grants",
    "profiles", "visibility_groups", "visibility_group_members",
    "profile_follows", "profile_blocks", "profile_hides",
    "captcha_challenges", "captcha_tokens",
    "policies", "policy_versions", "policy_rollouts",
    "data_requests",
    "master_records", "master_record_history", "audit_logs",
]


def test_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"


def test_healthz_db_unreachable(client, app):
    with patch("app.extensions.db.session.execute", side_effect=Exception("DB down")):
        resp = client.get("/healthz")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["db"] == "error"


def test_all_tables_created(app):
    from app.extensions import db
    with app.app_context():
        result = db.session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
        table_names = [row[0] for row in result]
        for table in EXPECTED_TABLES:
            assert table in table_names, f"Table '{table}' not found in database"


def test_unknown_route_returns_json(client):
    resp = client.get("/nonexistent")
    assert resp.status_code == 404
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    assert "error" in data


def test_method_not_allowed_returns_json(client):
    resp = client.delete("/healthz")
    assert resp.status_code == 405
    data = resp.get_json()
    assert "error" in data


def test_internal_error_returns_json(client, app):
    # /test-error is pre-registered in app factory when TESTING=True
    resp = client.get("/test-error")
    assert resp.status_code == 500
    data = resp.get_json()
    assert "error" in data
    assert "stack" not in str(data)


def test_wal_mode_enabled(app):
    from app.extensions import db
    with app.app_context():
        result = db.session.execute(text("PRAGMA journal_mode")).scalar()
        assert result == "wal"


def test_readme_exists(app):
    import os
    readme_path = os.path.join(os.path.dirname(__file__), "..", "README.md")
    assert os.path.exists(readme_path)
    with open(readme_path) as f:
        content = f.read()
    assert "docker compose up" in content


def test_env_var_table_in_readme(app):
    import os
    readme_path = os.path.join(os.path.dirname(__file__), "..", "README.md")
    with open(readme_path) as f:
        content = f.read()
    assert "FIELD_ENCRYPTION_KEY" in content
    assert "DATABASE_URL" in content
    assert "LOG_LEVEL" in content


def test_openapi_json_reachable(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    assert "openapi" in data
    assert "paths" in data


def test_swagger_ui_reachable(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    # Check HTML content
    assert b"swagger" in resp.data.lower() or b"openapi" in resp.data.lower()


def test_swagger_ui_no_cdn(client):
    resp = client.get("/docs")
    content = resp.data.decode("utf-8", errors="replace")
    assert "cdn." not in content
    assert "unpkg.com" not in content
    assert "jsdelivr" not in content


def test_bearer_auth_scheme_in_spec(client):
    resp = client.get("/openapi.json")
    data = resp.get_json()
    schemes = data.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" in schemes
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"


def test_openapi_all_routes_documented(client):
    resp = client.get("/openapi.json")
    data = resp.get_json()
    paths = data.get("paths", {})
    required_paths = [
        "/auth/login", "/assets", "/membership/me",
        "/policies", "/compliance/export-request", "/admin/audit-logs"
    ]
    for path in required_paths:
        assert any(p.startswith(path) or p == path for p in paths), \
            f"Path {path} not found in OpenAPI spec. Available: {list(paths.keys())}"
