import os
import pytest
import base64
import tempfile

os.environ.setdefault("FIELD_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())

from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    # Use a temp file-based SQLite so WAL mode works (WAL is unsupported on :memory:)
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    db_url = f"sqlite:///{db_path}"

    os.environ["DATABASE_URL"] = db_url

    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": db_url,
        "WTF_CSRF_ENABLED": False,
        # Use a very high memory-backed limit so rate-limit tests
        # don't bleed into fixture setup calls.
        "RATELIMIT_STORAGE_URI": "memory://",
    })
    with app.app_context():
        _db.create_all()
        from app.services.membership_service import seed_default_tiers
        seed_default_tiers()
        # Create sentinel user for compliance deletion (must exist before any test)
        from app.services.compliance_service import get_or_create_sentinel_user
        get_or_create_sentinel_user()
        yield app

    # Cleanup temp DB file
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope="function")
def client(app):
    # Reset rate-limit counters before each test so limits don't bleed across tests
    from app.extensions import limiter
    try:
        with app.app_context():
            limiter.reset()
    except Exception:
        pass
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper: register + login and return the token
# ---------------------------------------------------------------------------

def _register_and_login(client, username, email, password):
    client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    resp = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    data = resp.get_json()
    return data["token"]


def _create_user_direct(app, username, email, password):
    """Create a user directly in the DB and return a valid session token.

    This bypasses the HTTP register/login endpoints so rate-limit state
    accumulated by other tests does not interfere with fixture setup.
    """
    from app.services.auth_service import register_user, login_user

    with app.app_context():
        # register_user raises ValueError if username/email is already taken
        try:
            register_user(username=username, email=email, password=password)
        except ValueError:
            pass  # user already exists from a previous test run in same session

        session = login_user(username=username, password=password, ip="127.0.0.1")
        return session.token


def _make_admin(app, username):
    """Promote *username* to admin role (creates role if needed)."""
    from app.models.auth import User, Role, UserRole
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        role = Role.query.filter_by(name="admin").first()
        if role is None:
            role = Role(name="admin")
            _db.session.add(role)
            _db.session.flush()
        existing = UserRole.query.filter_by(user_id=user.id, role_id=role.id).first()
        if not existing:
            _db.session.add(UserRole(user_id=user.id, role_id=role.id))
        _db.session.commit()


@pytest.fixture(scope="function")
def user_token(client, app):
    """Create a regular user directly in the DB and return a session token."""
    token = _create_user_direct(
        app,
        username="fixtureuser",
        email="fixtureuser@example.com",
        password="FixturePass123!",
    )
    yield token


@pytest.fixture(scope="function")
def admin_token(client, app):
    """Create a user, promote to admin, and return their session token."""
    _create_user_direct(
        app,
        username="fixtureadmin",
        email="fixtureadmin@example.com",
        password="AdminPass123!",
    )
    _make_admin(app, "fixtureadmin")
    # Login again to get a fresh token (role assignment doesn't affect existing token validity)
    with app.app_context():
        from app.services.auth_service import login_user
        session = login_user(
            username="fixtureadmin",
            password="AdminPass123!",
            ip="127.0.0.1",
        )
        token = session.token
    yield token


@pytest.fixture(scope="function")
def seeded_db(app):
    """Insert ~10,000 rows across assets, ledger, risk_events for performance tests."""
    import uuid as _uuid
    from app.models.asset import Asset
    from app.models.membership import Ledger
    from app.models.risk import RiskEvent
    from app.extensions import db
    from app.models.auth import User
    from app.services.auth_service import register_user

    # Use a unique run prefix to avoid idempotency_key collisions across test runs
    run_prefix = _uuid.uuid4().hex

    with app.app_context():
        seed_user = User.query.filter_by(username='seed_user').first()
        if not seed_user:
            seed_user = register_user('seed_user', 'seed@test.com', 'seedpassword123')

        # Seed 3333 assets
        assets = []
        for i in range(3333):
            a = Asset(
                title=f"Asset {i}",
                asset_type="image",
                created_by=seed_user.id,
                metadata_json='{"width": 100, "height": 100, "format": "jpg"}'
            )
            assets.append(a)
        db.session.bulk_save_objects(assets)

        # Seed 3333 ledger entries with unique idempotency keys
        ledgers = []
        for i in range(3333):
            l = Ledger(
                user_id=seed_user.id,
                amount=100,
                currency="points",
                entry_type="credit",
                reason=f"seed_{i}",
                idempotency_key=f"seed_ledger_{run_prefix}_{i}"
            )
            ledgers.append(l)
        db.session.bulk_save_objects(ledgers)

        # Seed 3334 risk events
        events = []
        for i in range(3334):
            e = RiskEvent(
                event_type="test",
                ip="127.0.0.1",
                decision="allow",
                reasons="[]"
            )
            events.append(e)
        db.session.bulk_save_objects(events)

        db.session.commit()
        yield


@pytest.fixture(scope="function")
def moderator_token(client, app):
    """Create a moderator user directly in the DB and return a session token."""
    from app.models.auth import User, Role, UserRole
    token = _create_user_direct(
        app,
        username="fixturemoderator",
        email="fixturemoderator@example.com",
        password="ModeratorPass123!",
    )
    with app.app_context():
        user = User.query.filter_by(username="fixturemoderator").first()
        role = Role.query.filter_by(name="moderator").first()
        if role is None:
            role = Role(name="moderator")
            _db.session.add(role)
            _db.session.flush()
        existing = UserRole.query.filter_by(user_id=user.id, role_id=role.id).first()
        if not existing:
            _db.session.add(UserRole(user_id=user.id, role_id=role.id))
        _db.session.commit()
    yield token
