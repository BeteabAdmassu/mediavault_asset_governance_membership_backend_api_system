"""
Tests for Prompt 7: Asset Metadata & Taxonomy.
All 17 tests.
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_basics(client, admin_token):
    """
    Create the minimal taxonomy/dictionary fixtures needed by asset tests:
    - A root category
    - A source dictionary value
    - A copyright dictionary value
    Returns (category_id, source_value, copyright_value).
    """
    h = {"Authorization": f"Bearer {admin_token}"}

    # Category
    resp = client.post("/taxonomy/categories", json={"name": "Test Category", "level": 1}, headers=h)
    assert resp.status_code == 201, resp.get_json()
    category_id = resp.get_json()["id"]

    # Source
    resp = client.post(
        "/taxonomy/dictionaries",
        json={"dimension": "source", "value": "Reuters"},
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()

    # Copyright
    resp = client.post(
        "/taxonomy/dictionaries",
        json={"dimension": "copyright", "value": "CC-BY-4.0"},
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()

    return category_id, "Reuters", "CC-BY-4.0"


# ---------------------------------------------------------------------------
# Category tests
# ---------------------------------------------------------------------------

def test_create_category_root(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = client.post(
        "/taxonomy/categories",
        json={"name": "Root Category", "level": 1},
        headers=h,
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "Root Category"
    assert data["id"] is not None
    assert data["parent_id"] is None


def test_create_category_child(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    # Create parent
    resp = client.post(
        "/taxonomy/categories",
        json={"name": "Parent Cat", "level": 1},
        headers=h,
    )
    assert resp.status_code == 201
    parent_id = resp.get_json()["id"]

    # Create child
    resp = client.post(
        "/taxonomy/categories",
        json={"name": "Child Cat", "parent_id": parent_id, "level": 2},
        headers=h,
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["parent_id"] == parent_id
    assert data["name"] == "Child Cat"


def test_get_category_tree(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    # Create a root
    resp = client.post(
        "/taxonomy/categories",
        json={"name": "Tree Root", "level": 1},
        headers=h,
    )
    assert resp.status_code == 201
    root_id = resp.get_json()["id"]

    # Create a child
    client.post(
        "/taxonomy/categories",
        json={"name": "Tree Child", "parent_id": root_id, "level": 2},
        headers=h,
    )

    # Get tree
    resp = client.get("/taxonomy/categories", headers=h)
    assert resp.status_code == 200
    tree = resp.get_json()
    assert isinstance(tree, list)
    # Find our root in the tree
    roots_with_id = [n for n in tree if n["id"] == root_id]
    assert len(roots_with_id) == 1
    root_node = roots_with_id[0]
    assert "children" in root_node
    child_ids = [c["id"] for c in root_node["children"]]
    assert any(c["name"] == "Tree Child" for c in root_node["children"])


# ---------------------------------------------------------------------------
# Dictionary tests
# ---------------------------------------------------------------------------

def test_create_dictionary_value(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = client.post(
        "/taxonomy/dictionaries",
        json={"dimension": "source", "value": "AP News", "description": "Associated Press"},
        headers=h,
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["dimension"] == "source"
    assert data["value"] == "AP News"
    assert data["id"] is not None


# ---------------------------------------------------------------------------
# Asset creation tests
# ---------------------------------------------------------------------------

def test_create_asset_image_success(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Test Image",
            "asset_type": "image",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"width": 1920, "height": 1080, "format": "jpeg"},
        },
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert data["title"] == "Test Image"
    assert data["asset_type"] == "image"
    assert data["id"] is not None


def test_create_asset_video_success(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Test Video",
            "asset_type": "video",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"duration_seconds": 120, "format": "mp4", "resolution": "1080p"},
        },
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert data["asset_type"] == "video"


def test_create_asset_missing_type_field_video(client, admin_token):
    """Video without format → 422 with errors.format."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Bad Video",
            "asset_type": "video",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"duration_seconds": 60, "resolution": "720p"},
            # "format" is missing
        },
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "format" in data["errors"]
    assert "video" in data["errors"]["format"]


def test_create_asset_missing_type_field_document(client, admin_token):
    """Document without page_count → 422."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Bad Document",
            "asset_type": "document",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"format": "pdf"},
            # "page_count" missing
        },
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "page_count" in data["errors"]


def test_create_asset_missing_type_field_audio(client, admin_token):
    """Audio without duration_seconds → 422."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Bad Audio",
            "asset_type": "audio",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"format": "mp3"},
            # "duration_seconds" missing
        },
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "duration_seconds" in data["errors"]


def test_create_asset_unknown_source(client, admin_token):
    """Unknown source → 422."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Bad Source Asset",
            "asset_type": "image",
            "category_id": category_id,
            "source": "UnknownSource_XYZ",
            "copyright": copyright,
            "metadata": {"width": 100, "height": 100, "format": "png"},
        },
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "source" in data["errors"]


def test_create_asset_unknown_copyright(client, admin_token):
    """Unknown copyright → 422."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Bad Copyright Asset",
            "asset_type": "image",
            "category_id": category_id,
            "source": source,
            "copyright": "UnknownCopyright_XYZ",
            "metadata": {"width": 100, "height": 100, "format": "png"},
        },
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "copyright" in data["errors"]


def test_create_asset_unknown_tag(client, admin_token):
    """Tag not in tag table → 422."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Tagged Asset",
            "asset_type": "image",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"width": 100, "height": 100, "format": "png"},
            "tags": ["nonexistent-tag-xyz"],
        },
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "tags" in data["errors"]


# ---------------------------------------------------------------------------
# Update / delete / list tests
# ---------------------------------------------------------------------------

def test_update_asset_revalidates(client, admin_token):
    """PATCH with invalid source → 422."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    # Create valid video first
    resp = client.post(
        "/assets",
        json={
            "title": "Valid Video",
            "asset_type": "video",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"duration_seconds": 60, "format": "mp4", "resolution": "1080p"},
        },
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()
    asset_id = resp.get_json()["id"]

    # PATCH with invalid source
    resp = client.patch(
        f"/assets/{asset_id}",
        json={"source": "InvalidSourceXYZ"},
        headers=h,
    )
    assert resp.status_code == 422, resp.get_json()
    data = resp.get_json()
    assert "errors" in data
    assert "source" in data["errors"]


def test_soft_delete_asset(client, admin_token):
    """DELETE /assets/<id> soft-deletes; subsequent GET returns 404."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "To Delete",
            "asset_type": "image",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"width": 50, "height": 50, "format": "png"},
        },
        headers=h,
    )
    assert resp.status_code == 201
    asset_id = resp.get_json()["id"]

    # Delete
    resp = client.delete(f"/assets/{asset_id}", headers=h)
    assert resp.status_code == 200

    # Subsequent GET returns 404
    resp = client.get(f"/assets/{asset_id}", headers=h)
    assert resp.status_code == 404


def test_asset_list_filter_by_type(client, admin_token):
    """GET /assets?asset_type=image returns only images."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    # Create image
    client.post(
        "/assets",
        json={
            "title": "Filter Image",
            "asset_type": "image",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"width": 800, "height": 600, "format": "jpeg"},
        },
        headers=h,
    )

    # Create audio
    client.post(
        "/assets",
        json={
            "title": "Filter Audio",
            "asset_type": "audio",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"duration_seconds": 180, "format": "mp3"},
        },
        headers=h,
    )

    resp = client.get("/assets?asset_type=image", headers=h)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    for item in data["items"]:
        assert item["asset_type"] == "image"


def test_asset_master_record_created(client, admin_token, app):
    """After POST /assets, a MasterRecord with entity_type='asset' should exist."""
    h = {"Authorization": f"Bearer {admin_token}"}
    category_id, source, copyright = _setup_basics(client, admin_token)

    resp = client.post(
        "/assets",
        json={
            "title": "Master Record Test",
            "asset_type": "image",
            "category_id": category_id,
            "source": source,
            "copyright": copyright,
            "metadata": {"width": 1280, "height": 720, "format": "png"},
        },
        headers=h,
    )
    assert resp.status_code == 201, resp.get_json()
    asset_id = resp.get_json()["id"]

    with app.app_context():
        from app.models.audit import MasterRecord
        mr = MasterRecord.query.filter_by(entity_type="asset", entity_id=asset_id).first()
        assert mr is not None
        assert mr.current_status == "active"


def test_non_moderator_cannot_create_asset(client, user_token):
    """Regular user (no admin/moderator role) → 403."""
    h = {"Authorization": f"Bearer {user_token}"}
    resp = client.post(
        "/assets",
        json={
            "title": "Unauthorized",
            "asset_type": "image",
            "category_id": 1,
            "source": "Reuters",
            "copyright": "CC-BY-4.0",
            "metadata": {"width": 100, "height": 100, "format": "png"},
        },
        headers=h,
    )
    assert resp.status_code == 403
