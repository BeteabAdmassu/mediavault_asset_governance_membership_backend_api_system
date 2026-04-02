"""
Tests for Prompt 8: Profile, Privacy & Visibility Controls.
All 17 tests.
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(app, username, email, password="password123456"):
    """Register user via service (bypasses HTTP to avoid CAPTCHA/rate-limit)."""
    from app.services.auth_service import register_user, login_user
    with app.app_context():
        try:
            register_user(username=username, email=email, password=password)
        except ValueError:
            pass  # already exists
        session = login_user(username=username, password=password, ip="127.0.0.1")
        return session.token


def _get_user_id(app, username):
    from app.models.auth import User
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        return user.id


def _create_restricted_asset(client, admin_token):
    """Create a minimal restricted asset and return its id."""
    import uuid
    h = {"Authorization": f"Bearer {admin_token}"}

    # category (unique name each call to avoid conflicts)
    cat_name = f"DLCat-{uuid.uuid4().hex[:6]}"
    resp = client.post("/taxonomy/categories", json={"name": cat_name, "level": 1}, headers=h)
    assert resp.status_code == 201, resp.get_json()
    cat_id = resp.get_json()["id"]

    # source dictionary value (unique)
    src_val = f"SrcDL-{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/taxonomy/dictionaries",
        json={"dimension": "source", "value": src_val},
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()

    # copyright dictionary value (unique)
    cp_val = f"CpDL-{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/taxonomy/dictionaries",
        json={"dimension": "copyright", "value": cp_val},
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()

    resp = client.post(
        "/assets",
        json={
            "title": "Restricted Asset",
            "asset_type": "image",
            "category_id": cat_id,
            "source": src_val,
            "copyright": cp_val,
            "is_restricted": True,
            "metadata": {"width": 100, "height": 100, "format": "jpg"},
        },
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


# ---------------------------------------------------------------------------
# 1. Profile auto-created on register
# ---------------------------------------------------------------------------

def test_profile_auto_created_on_register(client, app):
    token = _make_user(app, "newreg_user", "newreg@test.com")
    user_id = _get_user_id(app, "newreg_user")
    with app.app_context():
        from app.models.profile import Profile
        profile = Profile.query.filter_by(user_id=user_id).first()
        assert profile is not None
        assert profile.display_name == "newreg_user"


# ---------------------------------------------------------------------------
# 2. Update own profile
# ---------------------------------------------------------------------------

def test_update_own_profile(client, user_token):
    resp = client.patch(
        "/profiles/me",
        json={"display_name": "Updated Name", "bio": "Hello!"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["display_name"] == "Updated Name"


# ---------------------------------------------------------------------------
# 3. Bio max length
# ---------------------------------------------------------------------------

def test_bio_max_length(client, user_token):
    long_bio = "x" * 501
    resp = client.patch(
        "/profiles/me",
        json={"bio": long_bio},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 4. Public scope visible to any user
# ---------------------------------------------------------------------------

def test_public_scope_visible_to_any_user(client, app):
    token_a = _make_user(app, "pub_user_a", "pub_a@test.com")
    token_b = _make_user(app, "pub_user_b", "pub_b@test.com")
    user_a_id = _get_user_id(app, "pub_user_a")

    # Ensure A's profile is public
    client.patch(
        "/profiles/me",
        json={"visibility_scope": "public"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # B views A's profile
    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "bio" in data  # full profile


# ---------------------------------------------------------------------------
# 5. Mutual followers scope – stub for non-mutual
# ---------------------------------------------------------------------------

def test_mutual_followers_scope_stub_for_non_mutual(client, app):
    token_a = _make_user(app, "mf_a1", "mf_a1@test.com")
    token_b = _make_user(app, "mf_b1", "mf_b1@test.com")
    user_a_id = _get_user_id(app, "mf_a1")
    user_b_id = _get_user_id(app, "mf_b1")

    # A sets mutual_followers scope
    client.patch(
        "/profiles/me",
        json={"visibility_scope": "mutual_followers"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # B follows A but A does NOT follow B
    client.post(
        f"/profiles/{user_a_id}/follow",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    # B views A's profile → should get stub
    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "bio" not in data
    assert "user_id" in data
    assert "display_name" in data


# ---------------------------------------------------------------------------
# 6. Mutual followers scope – full for mutual
# ---------------------------------------------------------------------------

def test_mutual_followers_scope_full_for_mutual(client, app):
    token_a = _make_user(app, "mf_a2", "mf_a2@test.com")
    token_b = _make_user(app, "mf_b2", "mf_b2@test.com")
    user_a_id = _get_user_id(app, "mf_a2")
    user_b_id = _get_user_id(app, "mf_b2")

    # A sets mutual_followers scope
    client.patch(
        "/profiles/me",
        json={"visibility_scope": "mutual_followers"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # A follows B, B follows A → mutual
    client.post(f"/profiles/{user_b_id}/follow", headers={"Authorization": f"Bearer {token_a}"})
    client.post(f"/profiles/{user_a_id}/follow", headers={"Authorization": f"Bearer {token_b}"})

    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "bio" in data  # full profile


# ---------------------------------------------------------------------------
# 7. Custom group scope – visible to member
# ---------------------------------------------------------------------------

def test_custom_group_scope_visible_to_member(client, app):
    token_a = _make_user(app, "cg_a1", "cg_a1@test.com")
    token_b = _make_user(app, "cg_b1", "cg_b1@test.com")
    user_a_id = _get_user_id(app, "cg_a1")
    user_b_id = _get_user_id(app, "cg_b1")

    # A creates a group with B as member
    resp = client.post(
        "/profiles/groups",
        json={"name": "MyGroup", "member_ids": [user_b_id]},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201, resp.get_json()
    group_id = resp.get_json()["id"]

    # A sets scope to custom_group and links group
    client.patch(
        "/profiles/me",
        json={"visibility_scope": "custom_group", "visibility_group_id": group_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # B views A's profile → full
    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "bio" in data


# ---------------------------------------------------------------------------
# 8. Custom group scope – stub for non-member
# ---------------------------------------------------------------------------

def test_custom_group_scope_stub_for_non_member(client, app):
    token_a = _make_user(app, "cg_a2", "cg_a2@test.com")
    token_b = _make_user(app, "cg_b2", "cg_b2@test.com")
    token_c = _make_user(app, "cg_c2", "cg_c2@test.com")
    user_a_id = _get_user_id(app, "cg_a2")
    user_b_id = _get_user_id(app, "cg_b2")

    # A creates a group with B only
    resp = client.post(
        "/profiles/groups",
        json={"name": "SelectiveGroup", "member_ids": [user_b_id]},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    group_id = resp.get_json()["id"]

    # A sets scope to custom_group
    client.patch(
        "/profiles/me",
        json={"visibility_scope": "custom_group", "visibility_group_id": group_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # C (not in group) views A's profile → stub
    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_c}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "bio" not in data
    assert "user_id" in data


# ---------------------------------------------------------------------------
# 9. Block hides profile (blocked user gets 403)
# ---------------------------------------------------------------------------

def test_block_hides_profile(client, app):
    token_a = _make_user(app, "blk_a1", "blk_a1@test.com")
    token_b = _make_user(app, "blk_b1", "blk_b1@test.com")
    user_a_id = _get_user_id(app, "blk_a1")
    user_b_id = _get_user_id(app, "blk_b1")

    # A blocks B
    resp = client.post(
        f"/profiles/{user_b_id}/block",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201

    # B tries to view A's profile → 403
    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 10. Blocked user cannot follow
# ---------------------------------------------------------------------------

def test_blocked_user_cannot_follow(client, app):
    token_a = _make_user(app, "blk_a2", "blk_a2@test.com")
    token_b = _make_user(app, "blk_b2", "blk_b2@test.com")
    user_a_id = _get_user_id(app, "blk_a2")
    user_b_id = _get_user_id(app, "blk_b2")

    # A blocks B
    client.post(
        f"/profiles/{user_b_id}/block",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # B tries to follow A → 403
    resp = client.post(
        f"/profiles/{user_a_id}/follow",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 11. Block is silent (no mention of "blocked" in response body)
# ---------------------------------------------------------------------------

def test_block_is_silent(client, app):
    token_a = _make_user(app, "blk_a3", "blk_a3@test.com")
    token_b = _make_user(app, "blk_b3", "blk_b3@test.com")
    user_a_id = _get_user_id(app, "blk_a3")
    user_b_id = _get_user_id(app, "blk_b3")

    # A blocks B
    client.post(
        f"/profiles/{user_b_id}/block",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # B views A's profile → 403 without "blocked" in message
    resp = client.get(
        f"/profiles/{user_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403
    body = resp.get_json()
    message = (body.get("message") or "").lower()
    assert "block" not in message


# ---------------------------------------------------------------------------
# 12. Hide user
# ---------------------------------------------------------------------------

def test_hide_user(client, app):
    token_a = _make_user(app, "hide_a1", "hide_a1@test.com")
    token_b = _make_user(app, "hide_b1", "hide_b1@test.com")
    user_b_id = _get_user_id(app, "hide_b1")

    resp = client.post(
        f"/profiles/{user_b_id}/hide",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["message"] == "hidden"


# ---------------------------------------------------------------------------
# 13. Follow / Unfollow
# ---------------------------------------------------------------------------

def test_follow_unfollow(client, app, user_token):
    token_b = _make_user(app, "fu_user_b", "fu_b@test.com")
    user_b_id = _get_user_id(app, "fu_user_b")

    # Follow
    resp = client.post(
        f"/profiles/{user_b_id}/follow",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201

    # Check followers of B
    resp = client.get("/profiles/me/followers", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 200
    followers = resp.get_json()["followers"]
    # Should include fixtureuser's id
    from app.models.auth import User
    with app.app_context():
        fixture_user = User.query.filter_by(username="fixtureuser").first()
        assert fixture_user.id in followers

    # Unfollow
    resp = client.delete(
        f"/profiles/{user_b_id}/follow",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 14. Restricted asset download denied
# ---------------------------------------------------------------------------

def test_restricted_asset_download_denied(client, app, admin_token, user_token):
    asset_id = _create_restricted_asset(client, admin_token)

    resp = client.get(
        f"/assets/{asset_id}/download",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 15. Restricted asset download granted
# ---------------------------------------------------------------------------

def test_restricted_asset_download_granted(client, app, admin_token, user_token):
    asset_id = _create_restricted_asset(client, admin_token)

    from app.models.auth import User
    with app.app_context():
        from app.services.auth_service import get_current_user
        from app.models.auth import Session
        # Get user id from token
        session = Session.query.filter_by(token=user_token).first()
        if session is None:
            # token might be in a different context; get it via service
            user = get_current_user(user_token)
            uid = user.id
        else:
            uid = session.user_id

    # Admin grants download
    resp = client.post(
        f"/assets/{asset_id}/grant-download",
        json={"user_id": uid},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.get_json()

    # User can now download
    resp = client.get(
        f"/assets/{asset_id}/download",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 16. Revoke download grant
# ---------------------------------------------------------------------------

def test_revoke_download_grant(client, app, admin_token, user_token):
    asset_id = _create_restricted_asset(client, admin_token)

    from app.models.auth import Session
    with app.app_context():
        session = Session.query.filter_by(token=user_token).first()
        uid = session.user_id if session else None

    if uid is None:
        with app.app_context():
            from app.services.auth_service import get_current_user
            user = get_current_user(user_token)
            uid = user.id

    # Grant
    client.post(
        f"/assets/{asset_id}/grant-download",
        json={"user_id": uid},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Revoke
    resp = client.delete(
        f"/assets/{asset_id}/grant-download/{uid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # User can no longer download
    resp = client.get(
        f"/assets/{asset_id}/download",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 17. Visibility group membership
# ---------------------------------------------------------------------------

def test_visibility_group_membership(client, app, user_token):
    token_b = _make_user(app, "vgm_user_b", "vgm_b@test.com")
    user_b_id = _get_user_id(app, "vgm_user_b")

    # Create group
    resp = client.post(
        "/profiles/groups",
        json={"name": "TestGroup", "member_ids": [user_b_id]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201, resp.get_json()
    group_id = resp.get_json()["id"]

    # Get group
    resp = client.get(
        f"/profiles/groups/{group_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert user_b_id in data["members"]

    # Add another member
    token_c = _make_user(app, "vgm_user_c", "vgm_c@test.com")
    user_c_id = _get_user_id(app, "vgm_user_c")

    resp = client.post(
        f"/profiles/groups/{group_id}/members",
        json={"user_id": user_c_id},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201

    # Remove a member
    resp = client.delete(
        f"/profiles/groups/{group_id}/members/{user_b_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200

    # Verify B is no longer in the group
    resp = client.get(
        f"/profiles/groups/{group_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = resp.get_json()
    assert user_b_id not in data["members"]
    assert user_c_id in data["members"]
