"""
Asset Metadata & Taxonomy service.
"""
import json
import os
from datetime import datetime, timezone

from app.extensions import db
from app.models.asset import Asset, Taxonomy, Dictionary


# ---------------------------------------------------------------------------
# Load asset rules
# ---------------------------------------------------------------------------

def _load_asset_rules():
    rules_path = os.path.join(os.path.dirname(__file__), "..", "data", "asset_rules.json")
    with open(rules_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Category (Taxonomy) CRUD
# ---------------------------------------------------------------------------

def create_category(name, parent_id=None, level=None):
    """Create taxonomy category. Return category."""
    cat = Taxonomy(
        name=name,
        taxonomy_type="category",
        parent_id=parent_id,
        level=level,
    )
    db.session.add(cat)
    db.session.commit()
    return cat


def _build_tree(categories, parent_id=None):
    result = []
    for cat in categories:
        if cat.parent_id == parent_id:
            node = {
                "id": cat.id,
                "name": cat.name,
                "level": cat.level,
                "children": _build_tree(categories, cat.id),
            }
            result.append(node)
    return result


def get_categories():
    """Return full category tree as nested structure."""
    cats = Taxonomy.query.filter_by(taxonomy_type="category", deleted_at=None).all()
    return _build_tree(cats)


def update_category(category_id, **kwargs):
    """Update category."""
    cat = Taxonomy.query.filter_by(id=category_id, taxonomy_type="category", deleted_at=None).first()
    if cat is None:
        raise LookupError(f"Category {category_id} not found")
    for key, value in kwargs.items():
        setattr(cat, key, value)
    db.session.commit()
    return cat


def delete_category(category_id):
    """Soft-delete category."""
    cat = Taxonomy.query.filter_by(id=category_id, taxonomy_type="category", deleted_at=None).first()
    if cat is None:
        raise LookupError(f"Category {category_id} not found")
    cat.deleted_at = datetime.now(timezone.utc)
    db.session.commit()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def create_tag(name):
    """Create taxonomy tag."""
    tag = Taxonomy(
        name=name,
        taxonomy_type="tag",
    )
    db.session.add(tag)
    db.session.commit()
    return tag


def get_tags():
    """Return flat list of tags."""
    return Taxonomy.query.filter_by(taxonomy_type="tag", deleted_at=None).all()


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------

VALID_DIMENSIONS = {"keyword", "topic", "subject", "audience", "timeliness", "source", "copyright"}


def create_dictionary_value(dimension, value, description=None):
    """Create dictionary entry. Dimension must be one of valid enums."""
    if dimension not in VALID_DIMENSIONS:
        raise ValueError(f"Invalid dimension '{dimension}'. Must be one of: {', '.join(sorted(VALID_DIMENSIONS))}")
    entry = Dictionary(
        dimension=dimension,
        value=value,
        description=description,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def get_dictionary_values(dimension):
    """Return all active values for a dimension."""
    return Dictionary.query.filter_by(dimension=dimension, deleted_at=None).all()


def delete_dictionary_value(dict_id):
    """Soft-delete (existing assets unaffected)."""
    entry = Dictionary.query.filter_by(id=dict_id, deleted_at=None).first()
    if entry is None:
        raise LookupError(f"Dictionary entry {dict_id} not found")
    entry.deleted_at = datetime.now(timezone.utc)
    db.session.commit()


# ---------------------------------------------------------------------------
# Asset validation helper
# ---------------------------------------------------------------------------

def _validate_asset_fields(asset_type, category_id, source, copyright, tags, keywords,
                            topic, subject, audience, timeliness, metadata, rules):
    """
    Validate asset fields against rules and dictionary.
    Returns dict of errors, empty if valid.
    """
    errors = {}

    # Validate type-specific required fields from metadata
    type_rules = rules.get(asset_type)
    if type_rules is None:
        errors["asset_type"] = f"Unknown asset_type '{asset_type}'"
        return errors

    type_fields = type_rules.get("type_fields", [])
    for field in type_fields:
        val = metadata.get(field) if metadata else None
        if val is None or val == "":
            errors[field] = f"required for asset_type={asset_type}"

    if errors:
        return errors

    # Validate source in dictionary
    valid_sources = [d.value for d in Dictionary.query.filter_by(dimension="source", deleted_at=None).all()]
    if source not in valid_sources:
        errors["source"] = f"'{source}' is not a valid source"

    # Validate copyright in dictionary
    valid_copyrights = [d.value for d in Dictionary.query.filter_by(dimension="copyright", deleted_at=None).all()]
    if copyright not in valid_copyrights:
        errors["copyright"] = f"'{copyright}' is not a valid copyright"

    # Validate tags
    if tags:
        existing_tag_names = {t.name for t in Taxonomy.query.filter_by(taxonomy_type="tag", deleted_at=None).all()}
        for tag_name in tags:
            if tag_name not in existing_tag_names:
                errors["tags"] = f"Tag '{tag_name}' does not exist"
                break

    # Validate keywords
    if keywords:
        valid_keywords = {d.value for d in Dictionary.query.filter_by(dimension="keyword", deleted_at=None).all()}
        for kw in keywords:
            if kw not in valid_keywords:
                errors["keywords"] = f"Keyword '{kw}' is not a valid keyword"
                break

    # Validate topic/subject/audience/timeliness against dictionaries
    dim_field_map = {
        "topic": topic,
        "subject": subject,
        "audience": audience,
        "timeliness": timeliness,
    }
    for dim, val in dim_field_map.items():
        if val is not None:
            valid_vals = {d.value for d in Dictionary.query.filter_by(dimension=dim, deleted_at=None).all()}
            if valid_vals and val not in valid_vals:
                errors[dim] = f"'{val}' is not a valid {dim}"

    return errors


# ---------------------------------------------------------------------------
# Asset CRUD
# ---------------------------------------------------------------------------

def create_asset(title, asset_type, category_id, source, copyright, created_by, **kwargs):
    """
    Create asset with full validation.
    Returns asset.
    """
    rules = _load_asset_rules()

    metadata = kwargs.get("metadata", {}) or {}
    tags = kwargs.get("tags", []) or []
    keywords = kwargs.get("keywords", []) or []
    topic = kwargs.get("topic")
    subject = kwargs.get("subject")
    audience = kwargs.get("audience")
    timeliness = kwargs.get("timeliness")
    description = kwargs.get("description")
    is_restricted = kwargs.get("is_restricted", False)

    errors = _validate_asset_fields(
        asset_type=asset_type,
        category_id=category_id,
        source=source,
        copyright=copyright,
        tags=tags,
        keywords=keywords,
        topic=topic,
        subject=subject,
        audience=audience,
        timeliness=timeliness,
        metadata=metadata,
        rules=rules,
    )

    if errors:
        raise ValueError(json.dumps({"errors": errors}))

    asset = Asset(
        title=title,
        asset_type=asset_type,
        category_id=category_id,
        source=source,
        copyright=copyright,
        description=description,
        metadata_json=json.dumps(metadata) if metadata else None,
        tags_json=json.dumps(tags) if tags else None,
        keywords_json=json.dumps(keywords) if keywords else None,
        topic=topic,
        subject=subject,
        audience=audience,
        timeliness=timeliness,
        is_restricted=is_restricted,
        created_by=created_by,
    )
    db.session.add(asset)
    db.session.flush()

    # Create MasterRecord
    from app.services.master_record_service import create_master_record
    create_master_record(
        entity_type="asset",
        entity_id=asset.id,
        initial_status="active",
        created_by=created_by,
    )

    db.session.commit()
    return asset


def get_assets(asset_type=None, category_id=None, tags=None, keywords=None,
               copyright=None, audience=None, page=1, per_page=20):
    """Paginated, filterable asset list. Excludes soft-deleted."""
    query = Asset.query.filter_by(deleted_at=None)

    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if category_id:
        query = query.filter(Asset.category_id == category_id)
    if copyright:
        query = query.filter(Asset.copyright == copyright)
    if audience:
        query = query.filter(Asset.audience == audience)
    if tags:
        # Filter assets that have any of the given tags
        for tag in tags:
            query = query.filter(Asset.tags_json.contains(tag))
    if keywords:
        for kw in keywords:
            query = query.filter(Asset.keywords_json.contains(kw))

    return query.paginate(page=page, per_page=per_page, error_out=False)


def get_asset(asset_id):
    """Get single asset (not deleted)."""
    asset = Asset.query.filter_by(id=asset_id, deleted_at=None).first()
    if asset is None:
        raise LookupError(f"Asset {asset_id} not found")
    return asset


def update_asset(asset_id, updated_by, **kwargs):
    """Partial update with re-validation of changed fields."""
    rules = _load_asset_rules()

    asset = Asset.query.filter_by(id=asset_id, deleted_at=None).first()
    if asset is None:
        raise LookupError(f"Asset {asset_id} not found")

    # Merge updated fields with existing values for re-validation
    asset_type = kwargs.get("asset_type", asset.asset_type)
    category_id = kwargs.get("category_id", asset.category_id)
    source = kwargs.get("source", asset.source)
    copyright = kwargs.get("copyright", asset.copyright)
    tags = kwargs.get("tags", json.loads(asset.tags_json) if asset.tags_json else [])
    keywords = kwargs.get("keywords", json.loads(asset.keywords_json) if asset.keywords_json else [])
    topic = kwargs.get("topic", asset.topic)
    subject = kwargs.get("subject", asset.subject)
    audience = kwargs.get("audience", asset.audience)
    timeliness = kwargs.get("timeliness", asset.timeliness)

    # Merge metadata
    existing_metadata = json.loads(asset.metadata_json) if asset.metadata_json else {}
    new_metadata = kwargs.get("metadata", {}) or {}
    merged_metadata = {**existing_metadata, **new_metadata}

    errors = _validate_asset_fields(
        asset_type=asset_type,
        category_id=category_id,
        source=source,
        copyright=copyright,
        tags=tags,
        keywords=keywords,
        topic=topic,
        subject=subject,
        audience=audience,
        timeliness=timeliness,
        metadata=merged_metadata,
        rules=rules,
    )

    if errors:
        raise ValueError(json.dumps({"errors": errors}))

    # Apply updates
    if "title" in kwargs:
        asset.title = kwargs["title"]
    if "asset_type" in kwargs:
        asset.asset_type = kwargs["asset_type"]
    if "category_id" in kwargs:
        asset.category_id = kwargs["category_id"]
    if "source" in kwargs:
        asset.source = kwargs["source"]
    if "copyright" in kwargs:
        asset.copyright = kwargs["copyright"]
    if "description" in kwargs:
        asset.description = kwargs["description"]
    if "metadata" in kwargs:
        asset.metadata_json = json.dumps(merged_metadata)
    if "tags" in kwargs:
        asset.tags_json = json.dumps(tags)
    if "keywords" in kwargs:
        asset.keywords_json = json.dumps(keywords)
    if "topic" in kwargs:
        asset.topic = topic
    if "subject" in kwargs:
        asset.subject = subject
    if "audience" in kwargs:
        asset.audience = audience
    if "timeliness" in kwargs:
        asset.timeliness = timeliness
    if "is_restricted" in kwargs:
        asset.is_restricted = kwargs["is_restricted"]

    asset.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return asset


def delete_asset(asset_id):
    """Soft-delete."""
    asset = Asset.query.filter_by(id=asset_id, deleted_at=None).first()
    if asset is None:
        raise LookupError(f"Asset {asset_id} not found")
    asset.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
