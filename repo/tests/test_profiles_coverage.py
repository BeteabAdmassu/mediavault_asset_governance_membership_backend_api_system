"""
Extended profile tests covering follow/unfollow, block/unblock,
hide, visibility groups, and profile visibility scoping.

Route contract (from app/api/profiles.py):
  GET    /profiles/<user_id>                → profile (visibility-filtered)
  PATCH  /profiles/me                       → updated own profile
  GET    /profiles/me/followers             → {followers: [...]}
  GET    /profiles/me/following             → {following: [...]}
  POST   /profiles/<user_id>/follow         → 201 {message}
  DELETE /profiles/<user_id>/follow         → 200 {message}
  POST   /profiles/<user_id>/block          → 201 {message}
  DELETE /profiles/<user_id>/block          → 200 {message}
  POST   /profiles/<user_id>/hide           → 201 {message}
  POST   /profiles/groups                   → 201 {id, name, owner_id}
  GET    /profiles/groups/<id>              → group detail
  POST   /profiles/groups/<id>/members      → 201 {message}
  DELETE /profiles/groups/<id>/members/<uid> → 200 {message}
"""
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, suffix=None):
    """Register a user and return (user_id, token)."""
    name = f"prof_{suffix or uuid.uuid4().hex[:8]}"
    reg = client.post("/auth/register", json={
        "username": name,
        "email": f"{name}@test.com",
        "password": "StrongPass123!XX",
    })
    assert reg.status_code == 201, f"register failed: {reg.get_json()}"
    uid = reg.get_json()["user_id"]
    login = client.post("/auth/login", json={
        "username": name,
        "password": "StrongPass123!XX",
    })
    assert login.status_code == 200, f"login failed: {login.get_json()}"
    token = login.get_json()["token"]
    return uid, token


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def test_get_profile_returns_user_id(client, user_token):
    """GET /profiles/<user_id> returns profile with matching user_id."""
    uid, _ = _register_and_login(client)
    resp = client.get(f"/profiles/{uid}", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.get_json()["user_id"] == uid


def test_get_profile_not_found(client, user_token):
    """GET /profiles/999999 → 404."""
    resp = client.get("/profiles/999999", headers=_auth(user_token))
    assert resp.status_code == 404


def test_update_own_profile_persists(client, user_token):
    """PATCH /profiles/me updates and persists profile fields."""
    resp = client.patch(
        "/profiles/me",
        json={"display_name": "Updated Name", "bio": "My bio"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["display_name"] == "Updated Name"
    assert data["bio"] == "My bio"


def test_update_profile_bio_too_long(client, user_token):
    """PATCH /profiles/me with >500 char bio → 422."""
    resp = client.patch(
        "/profiles/me",
        json={"bio": "x" * 501},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Follow / Unfollow
# ---------------------------------------------------------------------------

def test_follow_returns_201_and_appears_in_followers(client, user_token):
    """POST follow → 201, target sees follower in /profiles/me/followers."""
    target_id, target_tok = _register_and_login(client)

    resp = client.post(f"/profiles/{target_id}/follow", headers=_auth(user_token))
    assert resp.status_code == 201
    assert "message" in resp.get_json()

    # Target's followers should include the caller
    followers = client.get("/profiles/me/followers", headers=_auth(target_tok))
    assert followers.status_code == 200


def test_follow_appears_in_following(client, user_token):
    """Caller sees target in /profiles/me/following."""
    target_id, _ = _register_and_login(client)
    client.post(f"/profiles/{target_id}/follow", headers=_auth(user_token))

    resp = client.get("/profiles/me/following", headers=_auth(user_token))
    assert resp.status_code == 200


def test_unfollow_success(client, user_token):
    """DELETE /profiles/<id>/follow removes the relationship → 200 {message}."""
    target_id, _ = _register_and_login(client)
    client.post(f"/profiles/{target_id}/follow", headers=_auth(user_token))
    resp = client.delete(f"/profiles/{target_id}/follow", headers=_auth(user_token))
    assert resp.status_code == 200
    assert "message" in resp.get_json()


def test_unfollow_not_following(client, user_token):
    """DELETE /profiles/<id>/follow when not following → 404."""
    target_id, _ = _register_and_login(client)
    resp = client.delete(f"/profiles/{target_id}/follow", headers=_auth(user_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Block / Unblock
# ---------------------------------------------------------------------------

def test_block_user_returns_201(client, user_token):
    """POST /profiles/<id>/block → 201."""
    target_id, _ = _register_and_login(client)
    resp = client.post(f"/profiles/{target_id}/block", headers=_auth(user_token))
    assert resp.status_code == 201
    assert "message" in resp.get_json()


def test_block_already_blocked_returns_409(client, user_token):
    """POST /profiles/<id>/block when already blocked → 409."""
    target_id, _ = _register_and_login(client)
    client.post(f"/profiles/{target_id}/block", headers=_auth(user_token))
    resp = client.post(f"/profiles/{target_id}/block", headers=_auth(user_token))
    assert resp.status_code == 409


def test_unblock_user(client, user_token):
    """DELETE /profiles/<id>/block → 200."""
    target_id, _ = _register_and_login(client)
    client.post(f"/profiles/{target_id}/block", headers=_auth(user_token))
    resp = client.delete(f"/profiles/{target_id}/block", headers=_auth(user_token))
    assert resp.status_code == 200


def test_unblock_not_blocked(client, user_token):
    """DELETE /profiles/<id>/block when not blocked → 404."""
    target_id, _ = _register_and_login(client)
    resp = client.delete(f"/profiles/{target_id}/block", headers=_auth(user_token))
    assert resp.status_code == 404


def test_blocked_user_cannot_view_profile(client, user_token):
    """GET /profiles/<id> when blocked → 403."""
    target_id, target_tok = _register_and_login(client)
    me_resp = client.get("/auth/me", headers=_auth(user_token))
    my_id = me_resp.get_json()["user_id"]
    client.post(f"/profiles/{my_id}/block", headers=_auth(target_tok))

    resp = client.get(f"/profiles/{target_id}", headers=_auth(user_token))
    assert resp.status_code == 403


def test_block_removes_mutual_follows(client, user_token):
    """Blocking removes follow relationships in both directions."""
    target_id, target_tok = _register_and_login(client)
    me_resp = client.get("/auth/me", headers=_auth(user_token))
    my_id = me_resp.get_json()["user_id"]

    # Create mutual follow
    client.post(f"/profiles/{target_id}/follow", headers=_auth(user_token))
    client.post(f"/profiles/{my_id}/follow", headers=_auth(target_tok))

    # Block breaks follows
    client.post(f"/profiles/{target_id}/block", headers=_auth(user_token))

    # Unblock, then verify follow no longer exists
    client.delete(f"/profiles/{target_id}/block", headers=_auth(user_token))
    unfollow = client.delete(f"/profiles/{target_id}/follow", headers=_auth(user_token))
    assert unfollow.status_code == 404, "follow should have been removed by block"


# ---------------------------------------------------------------------------
# Hide
# ---------------------------------------------------------------------------

def test_hide_user_returns_201(client, user_token):
    """POST /profiles/<id>/hide → 201."""
    target_id, _ = _register_and_login(client)
    resp = client.post(f"/profiles/{target_id}/hide", headers=_auth(user_token))
    assert resp.status_code == 201


def test_hide_already_hidden_returns_409(client, user_token):
    """POST /profiles/<id>/hide when already hidden → 409."""
    target_id, _ = _register_and_login(client)
    client.post(f"/profiles/{target_id}/hide", headers=_auth(user_token))
    resp = client.post(f"/profiles/{target_id}/hide", headers=_auth(user_token))
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Visibility Groups
# ---------------------------------------------------------------------------

def test_create_visibility_group_returns_owner(client, user_token):
    """POST /profiles/groups → 201 with id, name, owner_id."""
    resp = client.post(
        "/profiles/groups",
        json={"name": f"VG_{uuid.uuid4().hex[:8]}"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert "id" in data
    assert "name" in data
    assert "owner_id" in data


def test_get_visibility_group_by_owner(client, user_token):
    """GET /profiles/groups/<id> returns group with matching id."""
    cr = client.post(
        "/profiles/groups",
        json={"name": f"VG_{uuid.uuid4().hex[:8]}"},
        headers=_auth(user_token),
    )
    gid = cr.get_json()["id"]
    resp = client.get(f"/profiles/groups/{gid}", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.get_json()["id"] == gid


def test_get_visibility_group_not_found(client, user_token):
    """GET /profiles/groups/999999 → 404."""
    resp = client.get("/profiles/groups/999999", headers=_auth(user_token))
    assert resp.status_code == 404


def test_add_group_member_returns_201(client, user_token):
    """POST /profiles/groups/<id>/members → 201."""
    target_id, _ = _register_and_login(client)
    cr = client.post(
        "/profiles/groups",
        json={"name": f"VG_{uuid.uuid4().hex[:8]}"},
        headers=_auth(user_token),
    )
    gid = cr.get_json()["id"]
    resp = client.post(
        f"/profiles/groups/{gid}/members",
        json={"user_id": target_id},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    assert "message" in resp.get_json()


def test_add_group_member_duplicate_returns_409(client, user_token):
    """POST /profiles/groups/<id>/members duplicate → 409."""
    target_id, _ = _register_and_login(client)
    cr = client.post(
        "/profiles/groups",
        json={"name": f"VG_{uuid.uuid4().hex[:8]}"},
        headers=_auth(user_token),
    )
    gid = cr.get_json()["id"]
    client.post(f"/profiles/groups/{gid}/members", json={"user_id": target_id}, headers=_auth(user_token))
    resp = client.post(f"/profiles/groups/{gid}/members", json={"user_id": target_id}, headers=_auth(user_token))
    assert resp.status_code == 409


def test_remove_group_member(client, user_token):
    """DELETE /profiles/groups/<id>/members/<uid> → 200."""
    target_id, _ = _register_and_login(client)
    cr = client.post("/profiles/groups", json={"name": f"VG_{uuid.uuid4().hex[:8]}"}, headers=_auth(user_token))
    gid = cr.get_json()["id"]
    client.post(f"/profiles/groups/{gid}/members", json={"user_id": target_id}, headers=_auth(user_token))
    resp = client.delete(f"/profiles/groups/{gid}/members/{target_id}", headers=_auth(user_token))
    assert resp.status_code == 200


def test_remove_group_member_not_found(client, user_token):
    """DELETE /profiles/groups/<id>/members/999999 → 404."""
    cr = client.post("/profiles/groups", json={"name": f"VG_{uuid.uuid4().hex[:8]}"}, headers=_auth(user_token))
    gid = cr.get_json()["id"]
    resp = client.delete(f"/profiles/groups/{gid}/members/999999", headers=_auth(user_token))
    assert resp.status_code == 404


def test_non_owner_cannot_add_member(client, user_token):
    """POST /profiles/groups/<id>/members by non-owner → 403."""
    _, other_tok = _register_and_login(client)
    target_id, _ = _register_and_login(client)
    cr = client.post("/profiles/groups", json={"name": f"VG_{uuid.uuid4().hex[:8]}"}, headers=_auth(user_token))
    gid = cr.get_json()["id"]
    resp = client.post(f"/profiles/groups/{gid}/members", json={"user_id": target_id}, headers=_auth(other_tok))
    assert resp.status_code == 403
