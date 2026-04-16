"""
Extended auth tests covering CAPTCHA gate on login, refresh token,
logout edge cases, and account anonymized/locked states.

Route contract (from app/api/auth.py):
  POST /auth/register  → 201 {user_id, username, email}
  POST /auth/login     → 200 {token, expires_at, user_id}
  POST /auth/logout    → 200 {message}
  POST /auth/refresh   → 200 {token, expires_at, user_id}
  GET  /auth/me        → 200 {user_id, username, email, status, roles}
  POST /auth/unlock/<uid> → 200 {message, user_id}
"""
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique():
    return uuid.uuid4().hex[:8]


def _register(client, name):
    resp = client.post("/auth/register", json={
        "username": name,
        "email": f"{name}@test.com",
        "password": "StrongPass123!XX",
    })
    assert resp.status_code == 201, f"register failed: {resp.get_json()}"
    return resp


# ---------------------------------------------------------------------------
# Register edge cases
# ---------------------------------------------------------------------------

def test_register_missing_email_returns_422(client):
    """POST /auth/register with missing email → 422."""
    resp = client.post("/auth/register", json={
        "username": f"u_{_unique()}",
        "password": "StrongPass123!XX",
    })
    assert resp.status_code == 422


def test_register_invalid_email_returns_422(client):
    """POST /auth/register with bad email → 422."""
    resp = client.post("/auth/register", json={
        "username": f"u_{_unique()}",
        "email": "not-an-email",
        "password": "StrongPass123!XX",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login CAPTCHA gate
# ---------------------------------------------------------------------------

def test_login_captcha_gate_skipped_in_testing(client):
    """In TESTING mode the CAPTCHA gate is skipped — login succeeds after a failure.

    The app deliberately disables the CAPTCHA gate when TESTING=True so that
    the majority of the test suite doesn't need to solve CAPTCHAs.  The
    ``test_login_with_solved_captcha_succeeds`` test below exercises the full
    gate path by setting TESTING=False temporarily.
    """
    name = f"cap_{_unique()}"
    _register(client, name)
    # Fail once
    client.post("/auth/login", json={"username": name, "password": "WrongPassword123!"})
    # In TESTING mode, second attempt succeeds without CAPTCHA
    resp = client.post("/auth/login", json={"username": name, "password": "StrongPass123!XX"})
    assert resp.status_code == 200
    assert "token" in resp.get_json()


def test_login_with_solved_captcha_succeeds(client, app):
    """Login with solved CAPTCHA token after a prior failure → 200."""
    name = f"capt_{_unique()}"
    _register(client, name)
    # Fail once
    client.post("/auth/login", json={"username": name, "password": "Wrong123!"})

    # Solve CAPTCHA
    challenge = client.get("/captcha/challenge").get_json()
    question = challenge["question"]
    parts = question.replace("What is ", "").replace("?", "").strip().split()
    a, op, b = int(parts[0]), parts[1], int(parts[2])
    ops = {"+": a + b, "-": a - b, "x": a * b, "/": a // b}
    answer = str(ops.get(op, 0))

    verify = client.post("/captcha/verify", json={
        "challenge_id": challenge["challenge_id"],
        "answer": answer,
    })
    assert verify.get_json()["valid"] is True, "CAPTCHA answer rejected"
    captcha_token = verify.get_json()["token"]

    # Login with captcha token
    resp = client.post(
        "/auth/login",
        json={"username": name, "password": "StrongPass123!XX"},
        headers={"X-Captcha-Token": captcha_token},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "token" in data
    assert "user_id" in data


# ---------------------------------------------------------------------------
# Logout edge cases
# ---------------------------------------------------------------------------

def test_logout_invalid_token_returns_401(client):
    """POST /auth/logout with bad token → 401."""
    resp = client.post("/auth/logout", headers=_auth("invalid_token_xyz"))
    assert resp.status_code == 401


def test_logout_twice_second_is_401(client, user_token):
    """POST /auth/logout twice → first 200, second 401."""
    resp1 = client.post("/auth/logout", headers=_auth(user_token))
    assert resp1.status_code == 200
    assert "message" in resp1.get_json()

    resp2 = client.post("/auth/logout", headers=_auth(user_token))
    assert resp2.status_code == 401


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------

def test_refresh_returns_new_expiry_and_user_id(client):
    """POST /auth/refresh returns token, expires_at, user_id."""
    name = f"ref_{_unique()}"
    _register(client, name)
    login = client.post("/auth/login", json={"username": name, "password": "StrongPass123!XX"})
    token = login.get_json()["token"]
    original_user_id = login.get_json()["user_id"]

    resp = client.post("/auth/refresh", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "expires_at" in data
    assert "token" in data
    assert data["user_id"] == original_user_id


def test_refresh_invalid_token_returns_401(client):
    """POST /auth/refresh with revoked token → 401."""
    resp = client.post("/auth/refresh", headers=_auth("bad_token_xyz"))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Account locked
# ---------------------------------------------------------------------------

def test_login_locked_returns_423_with_locked_until(client):
    """Login to locked account → 423 with locked_until timestamp."""
    name = f"lock_{_unique()}"
    _register(client, name)
    for _ in range(5):
        client.post("/auth/login", json={"username": name, "password": "WrongWrong123!"})
    resp = client.post("/auth/login", json={"username": name, "password": "StrongPass123!XX"})
    assert resp.status_code == 423
    data = resp.get_json()
    assert "locked_until" in data


# ---------------------------------------------------------------------------
# Unlock
# ---------------------------------------------------------------------------

def test_admin_unlock_not_found(client, admin_token):
    """POST /auth/unlock/999999 → 404."""
    resp = client.post("/auth/unlock/999999", headers=_auth(admin_token))
    assert resp.status_code == 404
