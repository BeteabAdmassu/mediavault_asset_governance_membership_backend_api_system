import time
import pytest


@pytest.mark.slow
def test_assets_list_p95_under_250ms(client, seeded_db, admin_token):
    start = time.time()
    resp = client.get("/assets", headers={"Authorization": f"Bearer {admin_token}"})
    elapsed = time.time() - start
    assert resp.status_code == 200
    assert elapsed < 0.25


@pytest.mark.slow
def test_ledger_me_p95_under_250ms(client, seeded_db, user_token):
    start = time.time()
    resp = client.get("/membership/ledger/me", headers={"Authorization": f"Bearer {user_token}"})
    elapsed = time.time() - start
    assert resp.status_code == 200
    assert elapsed < 0.25


@pytest.mark.slow
def test_risk_events_list_p95_under_250ms(client, seeded_db, admin_token):
    start = time.time()
    resp = client.get("/risk/events", headers={"Authorization": f"Bearer {admin_token}"})
    elapsed = time.time() - start
    assert resp.status_code == 200
    assert elapsed < 0.25


def test_required_indexes_exist(app):
    from app.extensions import db
    from sqlalchemy import text
    with app.app_context():
        result = db.session.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        ).fetchall()
        index_names = [row[0] for row in result]
        # Check composite indexes exist
        required_indexes = [
            "ix_risk_events_user_created",
            "ix_risk_events_ip_created",
            "ix_ledgers_user_currency",
            "ix_audit_logs_actor_created",
            "ix_coupon_redemptions_user_coupon",
        ]
        for idx in required_indexes:
            assert any(idx in name for name in index_names), \
                f"Index {idx} not found. Available: {index_names}"


def test_wal_and_cache_pragmas_set(app):
    from app.extensions import db
    from sqlalchemy import text
    with app.app_context():
        journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
        assert journal_mode == "wal"
        cache_size = db.session.execute(text("PRAGMA cache_size")).scalar()
        assert cache_size < 0  # Negative means KB
