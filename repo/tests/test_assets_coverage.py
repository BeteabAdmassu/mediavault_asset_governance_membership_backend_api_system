"""
Extended asset/taxonomy tests covering category update/delete,
tag CRUD, dictionary validation, asset update with re-validation,
download grant flows, and restricted asset access.

Route contract (from app/api/assets.py):
  POST   /taxonomy/categories         → 201 {id, name, …}
  GET    /taxonomy/categories         → category tree
  PATCH  /taxonomy/categories/<id>    → 200 updated
  DELETE /taxonomy/categories/<id>    → 200 {message}
  POST   /taxonomy/tags               → 201 {id, name, …}
  GET    /taxonomy/tags               → list
  POST   /taxonomy/dictionaries       → 201 {id, dimension, value, …}
  GET    /taxonomy/dictionaries?dim=  → list
  DELETE /taxonomy/dictionaries/<id>  → 200 {message}
  POST   /assets                      → 201 full asset
  GET    /assets                      → paginated
  GET    /assets/<id>                 → single asset
  PATCH  /assets/<id>                 → 200 updated
  DELETE /assets/<id>                 → 200 {message}
  POST   /assets/<id>/grant-download  → 201 {message, asset_id, user_id}
  GET    /assets/<id>/download        → 200 asset data or 403
"""
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _setup_taxonomy(client, admin_token):
    """Create category + source + copyright dictionaries. Returns (cat_id, source, copyright)."""
    h = _auth(admin_token)
    cat = client.post("/taxonomy/categories", json={"name": f"Cat_{uuid.uuid4().hex[:6]}"}, headers=h)
    assert cat.status_code == 201
    cat_id = cat.get_json()["id"]
    client.post("/taxonomy/dictionaries", json={"dimension": "source", "value": "Reuters"}, headers=h)
    client.post("/taxonomy/dictionaries", json={"dimension": "copyright", "value": "CC-BY-4.0"}, headers=h)
    return cat_id, "Reuters", "CC-BY-4.0"


def _create_image_asset(client, admin_token, cat_id):
    h = _auth(admin_token)
    resp = client.post("/assets", json={
        "title": f"Img_{uuid.uuid4().hex[:6]}",
        "asset_type": "image",
        "category_id": cat_id,
        "source": "Reuters",
        "copyright": "CC-BY-4.0",
        "metadata": {"width": 800, "height": 600, "format": "jpg"},
    }, headers=h)
    assert resp.status_code == 201, f"asset create failed: {resp.get_json()}"
    return resp


# ---------------------------------------------------------------------------
# Category CRUD
# ---------------------------------------------------------------------------

def test_category_update_persists(client, admin_token):
    """PATCH /taxonomy/categories/<id> updates and returns new name."""
    h = _auth(admin_token)
    cat = client.post("/taxonomy/categories", json={"name": f"CU_{uuid.uuid4().hex[:6]}"}, headers=h)
    cid = cat.get_json()["id"]
    resp = client.patch(f"/taxonomy/categories/{cid}", json={"name": "Updated Category"}, headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Updated Category"


def test_category_update_not_found(client, admin_token):
    """PATCH /taxonomy/categories/999999 → 404."""
    resp = client.patch("/taxonomy/categories/999999", json={"name": "nope"}, headers=_auth(admin_token))
    assert resp.status_code == 404


def test_category_delete_returns_message(client, admin_token):
    """DELETE /taxonomy/categories/<id> → 200 {message}."""
    h = _auth(admin_token)
    cat = client.post("/taxonomy/categories", json={"name": f"CD_{uuid.uuid4().hex[:6]}"}, headers=h)
    cid = cat.get_json()["id"]
    resp = client.delete(f"/taxonomy/categories/{cid}", headers=h)
    assert resp.status_code == 200
    assert "message" in resp.get_json()


def test_category_delete_not_found(client, admin_token):
    """DELETE /taxonomy/categories/999999 → 404."""
    resp = client.delete("/taxonomy/categories/999999", headers=_auth(admin_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def test_create_tag_returns_id_and_name(client, admin_token):
    """POST /taxonomy/tags → 201 with id and name."""
    tag_name = f"tag_{uuid.uuid4().hex[:6]}"
    resp = client.post("/taxonomy/tags", json={"name": tag_name}, headers=_auth(admin_token))
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == tag_name
    assert "id" in data


def test_list_tags_returns_array(client, admin_token):
    """GET /taxonomy/tags returns a list."""
    resp = client.get("/taxonomy/tags", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------

def test_dictionary_list_by_dimension_returns_matching(client, admin_token):
    """GET /taxonomy/dictionaries?dimension=source returns values for that dimension."""
    h = _auth(admin_token)
    val = f"AP_{uuid.uuid4().hex[:4]}"
    client.post("/taxonomy/dictionaries", json={"dimension": "source", "value": val}, headers=h)
    resp = client.get("/taxonomy/dictionaries?dimension=source", headers=h)
    assert resp.status_code == 200
    items = resp.get_json()
    assert isinstance(items, list)
    assert any(v["value"] == val for v in items)


def test_dictionary_delete_returns_message(client, admin_token):
    """DELETE /taxonomy/dictionaries/<id> → 200 {message}."""
    h = _auth(admin_token)
    cr = client.post("/taxonomy/dictionaries", json={"dimension": "source", "value": f"Del_{uuid.uuid4().hex[:4]}"}, headers=h)
    did = cr.get_json()["id"]
    resp = client.delete(f"/taxonomy/dictionaries/{did}", headers=h)
    assert resp.status_code == 200
    assert "message" in resp.get_json()


def test_dictionary_delete_not_found(client, admin_token):
    """DELETE /taxonomy/dictionaries/999999 → 404."""
    resp = client.delete("/taxonomy/dictionaries/999999", headers=_auth(admin_token))
    assert resp.status_code == 404


def test_dictionary_invalid_dimension_returns_422(client, admin_token):
    """POST /taxonomy/dictionaries with invalid dimension → 422."""
    resp = client.post(
        "/taxonomy/dictionaries",
        json={"dimension": "invalid_xyz", "value": "test"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Asset CRUD
# ---------------------------------------------------------------------------

def test_asset_get_returns_full_object(client, admin_token):
    """GET /assets/<id> returns all expected keys."""
    cat_id, _, _ = _setup_taxonomy(client, admin_token)
    cr = _create_image_asset(client, admin_token, cat_id)
    aid = cr.get_json()["id"]
    resp = client.get(f"/assets/{aid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == aid
    for key in ("title", "asset_type", "category_id", "source", "copyright", "created_at"):
        assert key in data


def test_asset_get_not_found(client, admin_token):
    """GET /assets/999999 → 404."""
    resp = client.get("/assets/999999", headers=_auth(admin_token))
    assert resp.status_code == 404


def test_asset_update_persists(client, admin_token):
    """PATCH /assets/<id> persists changes verifiable via GET."""
    cat_id, _, _ = _setup_taxonomy(client, admin_token)
    cr = _create_image_asset(client, admin_token, cat_id)
    aid = cr.get_json()["id"]
    resp = client.patch(
        f"/assets/{aid}",
        json={"title": "Updated Title", "description": "New desc"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Updated Title"

    # Verify via GET
    get_resp = client.get(f"/assets/{aid}", headers=_auth(admin_token))
    assert get_resp.get_json()["title"] == "Updated Title"
    assert get_resp.get_json()["description"] == "New desc"


def test_asset_update_not_found(client, admin_token):
    """PATCH /assets/999999 → 404."""
    resp = client.patch("/assets/999999", json={"title": "Nope"}, headers=_auth(admin_token))
    assert resp.status_code == 404


def test_asset_delete_and_verify_gone(client, admin_token):
    """DELETE /assets/<id> soft-deletes; subsequent GET → 404."""
    cat_id, _, _ = _setup_taxonomy(client, admin_token)
    cr = _create_image_asset(client, admin_token, cat_id)
    aid = cr.get_json()["id"]
    resp = client.delete(f"/assets/{aid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert "message" in resp.get_json()

    assert client.get(f"/assets/{aid}", headers=_auth(admin_token)).status_code == 404


def test_asset_delete_not_found(client, admin_token):
    """DELETE /assets/999999 → 404."""
    resp = client.delete("/assets/999999", headers=_auth(admin_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Restricted asset download flow
# ---------------------------------------------------------------------------

def test_restricted_asset_denied_without_grant(client, admin_token, user_token):
    """GET /assets/<id>/download on restricted asset without grant → 403."""
    cat_id, _, _ = _setup_taxonomy(client, admin_token)
    cr = client.post("/assets", json={
        "title": "Restricted", "asset_type": "image", "category_id": cat_id,
        "source": "Reuters", "copyright": "CC-BY-4.0",
        "metadata": {"width": 100, "height": 100, "format": "png"},
        "is_restricted": True,
    }, headers=_auth(admin_token))
    aid = cr.get_json()["id"]
    resp = client.get(f"/assets/{aid}/download", headers=_auth(user_token))
    assert resp.status_code == 403


def test_restricted_asset_granted_access(client, admin_token, user_token):
    """GET /assets/<id>/download after grant → 200."""
    cat_id, _, _ = _setup_taxonomy(client, admin_token)
    cr = client.post("/assets", json={
        "title": "Granted", "asset_type": "image", "category_id": cat_id,
        "source": "Reuters", "copyright": "CC-BY-4.0",
        "metadata": {"width": 100, "height": 100, "format": "png"},
        "is_restricted": True,
    }, headers=_auth(admin_token))
    aid = cr.get_json()["id"]

    me = client.get("/auth/me", headers=_auth(user_token))
    uid = me.get_json()["user_id"]

    grant = client.post(f"/assets/{aid}/grant-download", json={"user_id": uid}, headers=_auth(admin_token))
    assert grant.status_code == 201
    assert grant.get_json()["asset_id"] == aid
    assert grant.get_json()["user_id"] == uid

    resp = client.get(f"/assets/{aid}/download", headers=_auth(user_token))
    assert resp.status_code == 200


def test_unrestricted_asset_download(client, admin_token, user_token):
    """GET /assets/<id>/download on unrestricted asset → 200."""
    cat_id, _, _ = _setup_taxonomy(client, admin_token)
    cr = _create_image_asset(client, admin_token, cat_id)
    aid = cr.get_json()["id"]
    resp = client.get(f"/assets/{aid}/download", headers=_auth(user_token))
    assert resp.status_code == 200


def test_asset_download_not_found(client, admin_token):
    """GET /assets/999999/download → 404."""
    resp = client.get("/assets/999999/download", headers=_auth(admin_token))
    assert resp.status_code == 404


def test_asset_list_pagination_shape(client, admin_token):
    """GET /assets returns proper pagination envelope."""
    resp = client.get("/assets", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("items", "total", "page", "per_page", "pages"):
        assert key in data
