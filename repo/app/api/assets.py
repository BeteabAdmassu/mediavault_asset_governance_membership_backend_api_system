"""
Asset Metadata & Taxonomy API blueprint.
"""
import json

import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role, get_user_rate_key
from app.extensions import limiter

blp = flask_smorest.Blueprint(
    "assets",
    "assets",
    url_prefix="",
    description="Asset metadata, taxonomy, and dictionary management",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CategorySchema(ma.Schema):
    id = ma.fields.Int(dump_only=True)
    name = ma.fields.Str(required=True)
    parent_id = ma.fields.Int(allow_none=True, load_default=None)
    level = ma.fields.Int(allow_none=True, load_default=None)


class CategoryUpdateSchema(ma.Schema):
    name = ma.fields.Str()
    parent_id = ma.fields.Int(allow_none=True)
    level = ma.fields.Int(allow_none=True)


class TagSchema(ma.Schema):
    id = ma.fields.Int(dump_only=True)
    name = ma.fields.Str(required=True)


class DictionarySchema(ma.Schema):
    id = ma.fields.Int(dump_only=True)
    dimension = ma.fields.Str(required=True)
    value = ma.fields.Str(required=True)
    description = ma.fields.Str(allow_none=True, load_default=None)


class AssetCreateSchema(ma.Schema):
    title = ma.fields.Str(required=True)
    asset_type = ma.fields.Str(required=True)
    category_id = ma.fields.Int(required=True)
    source = ma.fields.Str(required=True)
    copyright = ma.fields.Str(required=True)
    description = ma.fields.Str(allow_none=True, load_default=None)
    metadata = ma.fields.Dict(load_default=None)
    tags = ma.fields.List(ma.fields.Str(), load_default=None)
    keywords = ma.fields.List(ma.fields.Str(), load_default=None)
    topic = ma.fields.Str(allow_none=True, load_default=None)
    subject = ma.fields.Str(allow_none=True, load_default=None)
    audience = ma.fields.Str(allow_none=True, load_default=None)
    timeliness = ma.fields.Str(allow_none=True, load_default=None)
    is_restricted = ma.fields.Bool(load_default=False)


class AssetUpdateSchema(ma.Schema):
    title = ma.fields.Str()
    asset_type = ma.fields.Str()
    category_id = ma.fields.Int()
    source = ma.fields.Str()
    copyright = ma.fields.Str()
    description = ma.fields.Str(allow_none=True)
    metadata = ma.fields.Dict(allow_none=True)
    tags = ma.fields.List(ma.fields.Str())
    keywords = ma.fields.List(ma.fields.Str())
    topic = ma.fields.Str(allow_none=True)
    subject = ma.fields.Str(allow_none=True)
    audience = ma.fields.Str(allow_none=True)
    timeliness = ma.fields.Str(allow_none=True)
    is_restricted = ma.fields.Bool()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _category_dict(cat):
    return {
        "id": cat.id,
        "name": cat.name,
        "taxonomy_type": cat.taxonomy_type,
        "parent_id": cat.parent_id,
        "level": cat.level,
        "created_at": cat.created_at.isoformat() if cat.created_at else None,
    }


def _tag_dict(tag):
    return {
        "id": tag.id,
        "name": tag.name,
        "taxonomy_type": tag.taxonomy_type,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


def _dict_entry_dict(entry):
    return {
        "id": entry.id,
        "dimension": entry.dimension,
        "value": entry.value,
        "description": entry.description,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _asset_dict(asset):
    return {
        "id": asset.id,
        "title": asset.title,
        "asset_type": asset.asset_type,
        "category_id": asset.category_id,
        "source": asset.source,
        "copyright": asset.copyright,
        "description": asset.description,
        "metadata": json.loads(asset.metadata_json) if asset.metadata_json else None,
        "tags": json.loads(asset.tags_json) if asset.tags_json else [],
        "keywords": json.loads(asset.keywords_json) if asset.keywords_json else [],
        "topic": asset.topic,
        "subject": asset.subject,
        "audience": asset.audience,
        "timeliness": asset.timeliness,
        "is_restricted": asset.is_restricted,
        "created_by": asset.created_by,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Taxonomy - Categories
# ---------------------------------------------------------------------------

@blp.route("/taxonomy/categories")
class CategoriesView(MethodView):
    @blp.doc(
        summary="Create a taxonomy category (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CategorySchema)
    @require_auth
    @require_role("admin", "moderator")
    def post(self, data):
        from app.services.asset_service import create_category
        cat = create_category(
            name=data["name"],
            parent_id=data.get("parent_id"),
            level=data.get("level"),
        )
        return jsonify(_category_dict(cat)), 201

    @blp.doc(
        summary="Get all taxonomy categories as a tree",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin", "moderator")
    def get(self):
        from app.services.asset_service import get_categories
        tree = get_categories()
        return jsonify(tree), 200


@blp.route("/taxonomy/categories/<int:id>")
class CategoryDetailView(MethodView):
    @blp.doc(
        summary="Update a taxonomy category (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CategoryUpdateSchema)
    @require_auth
    @require_role("admin", "moderator")
    def patch(self, data, id):
        from app.services.asset_service import update_category
        try:
            cat = update_category(id, **data)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_category_dict(cat)), 200

    @blp.doc(
        summary="Soft-delete a taxonomy category (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin", "moderator")
    def delete(self, id):
        from app.services.asset_service import delete_category
        try:
            delete_category(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"message": "Category deleted"}), 200


# ---------------------------------------------------------------------------
# Taxonomy - Tags
# ---------------------------------------------------------------------------

@blp.route("/taxonomy/tags")
class TagsView(MethodView):
    @blp.doc(
        summary="Create a taxonomy tag (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(TagSchema)
    @require_auth
    @require_role("admin", "moderator")
    def post(self, data):
        from app.services.asset_service import create_tag
        tag = create_tag(name=data["name"])
        return jsonify(_tag_dict(tag)), 201

    @blp.doc(
        summary="Get all taxonomy tags",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin", "moderator")
    def get(self):
        from app.services.asset_service import get_tags
        tags = get_tags()
        return jsonify([_tag_dict(t) for t in tags]), 200


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------

@blp.route("/taxonomy/dictionaries")
class DictionaryView(MethodView):
    @blp.doc(
        summary="Create a dictionary value (Admin)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(DictionarySchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.asset_service import create_dictionary_value
        try:
            entry = create_dictionary_value(
                dimension=data["dimension"],
                value=data["value"],
                description=data.get("description"),
            )
        except ValueError as exc:
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_dict_entry_dict(entry)), 201

    @blp.doc(
        summary="Get dictionary values (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.asset_service import get_dictionary_values
        dimension = request.args.get("dimension")
        if not dimension:
            return jsonify({"error": "bad_request", "message": "dimension query param required"}), 400
        entries = get_dictionary_values(dimension)
        return jsonify([_dict_entry_dict(e) for e in entries]), 200


@blp.route("/taxonomy/dictionaries/<int:id>")
class DictionaryDetailView(MethodView):
    @blp.doc(
        summary="Soft-delete a dictionary value (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def delete(self, id):
        from app.services.asset_service import delete_dictionary_value
        try:
            delete_dictionary_value(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"message": "Dictionary value deleted"}), 200


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@blp.route("/assets")
class AssetsView(MethodView):
    @blp.doc(
        summary="Create an asset (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(AssetCreateSchema)
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    @require_role("admin", "moderator")
    def post(self, data):
        from app.services.asset_service import create_asset
        user = g.current_user
        try:
            asset = create_asset(
                title=data["title"],
                asset_type=data["asset_type"],
                category_id=data["category_id"],
                source=data["source"],
                copyright=data["copyright"],
                created_by=user.id,
                description=data.get("description"),
                metadata=data.get("metadata") or {},
                tags=data.get("tags") or [],
                keywords=data.get("keywords") or [],
                topic=data.get("topic"),
                subject=data.get("subject"),
                audience=data.get("audience"),
                timeliness=data.get("timeliness"),
                is_restricted=data.get("is_restricted", False),
            )
        except ValueError as exc:
            try:
                error_data = json.loads(str(exc))
                return jsonify(error_data), 422
            except (json.JSONDecodeError, Exception):
                return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_asset_dict(asset)), 201

    @blp.doc(
        summary="List assets (authenticated)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @limiter.limit("300/minute", key_func=get_user_rate_key)
    def get(self):
        from app.services.asset_service import get_assets
        asset_type = request.args.get("asset_type")
        category_id = request.args.get("category_id", type=int)
        tags_param = request.args.getlist("tags")
        keywords_param = request.args.getlist("keywords")
        copyright_param = request.args.get("copyright")
        audience_param = request.args.get("audience")
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        pagination = get_assets(
            asset_type=asset_type,
            category_id=category_id,
            tags=tags_param or None,
            keywords=keywords_param or None,
            copyright=copyright_param,
            audience=audience_param,
            page=page,
            per_page=per_page,
        )

        return jsonify({
            "items": [_asset_dict(a) for a in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/assets/<int:id>")
class AssetDetailView(MethodView):
    @blp.doc(
        summary="Get a single asset (authenticated)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def get(self, id):
        from app.services.asset_service import get_asset
        try:
            asset = get_asset(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_asset_dict(asset)), 200

    @blp.doc(
        summary="Update an asset (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(AssetUpdateSchema)
    @require_auth
    @require_role("admin", "moderator")
    def patch(self, data, id):
        from app.services.asset_service import update_asset
        user = g.current_user
        try:
            asset = update_asset(id, updated_by=user.id, **data)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ValueError as exc:
            try:
                error_data = json.loads(str(exc))
                return jsonify(error_data), 422
            except (json.JSONDecodeError, Exception):
                return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_asset_dict(asset)), 200

    @blp.doc(
        summary="Soft-delete an asset (Admin only)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def delete(self, id):
        from app.services.asset_service import delete_asset
        try:
            delete_asset(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"message": "Asset deleted"}), 200


# ---------------------------------------------------------------------------
# Download Grant schemas
# ---------------------------------------------------------------------------

class GrantDownloadSchema(ma.Schema):
    user_id = ma.fields.Int(required=True)


# ---------------------------------------------------------------------------
# Download Grant / Restricted asset download
# ---------------------------------------------------------------------------

@blp.route("/assets/<int:id>/grant-download")
class AssetGrantDownloadView(MethodView):
    @blp.doc(
        summary="Grant download permission for a restricted asset (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(GrantDownloadSchema)
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    @require_role("admin", "moderator")
    def post(self, data, id):
        from app.models.asset import Asset, DownloadGrant
        from app.extensions import db
        from sqlalchemy.exc import IntegrityError

        asset = db.session.get(Asset, id)
        if asset is None or asset.deleted_at is not None:
            return jsonify({"error": "not_found", "message": "asset_not_found"}), 404

        try:
            grant = DownloadGrant(
                asset_id=id,
                user_id=data["user_id"],
                granted_by=g.current_user.id,
            )
            db.session.add(grant)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "conflict", "message": "grant_already_exists"}), 409

        return jsonify({"message": "grant created", "asset_id": id, "user_id": data["user_id"]}), 201


@blp.route("/assets/<int:id>/grant-download/<int:user_id>")
class AssetGrantDownloadDetailView(MethodView):
    @blp.doc(
        summary="Revoke download permission for a restricted asset (Admin/Moderator)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    @require_role("admin", "moderator")
    def delete(self, id, user_id):
        from app.models.asset import DownloadGrant
        from app.extensions import db

        grant = DownloadGrant.query.filter_by(asset_id=id, user_id=user_id).first()
        if grant is None:
            return jsonify({"error": "not_found", "message": "grant_not_found"}), 404

        db.session.delete(grant)
        db.session.commit()
        return jsonify({"message": "grant revoked"}), 200


@blp.route("/assets/<int:id>/download")
class AssetDownloadView(MethodView):
    @blp.doc(
        summary="Download/access a potentially restricted asset (authenticated)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def get(self, id):
        from app.models.asset import Asset, DownloadGrant
        from app.extensions import db

        asset = db.session.get(Asset, id)
        if asset is None or asset.deleted_at is not None:
            return jsonify({"error": "not_found", "message": "asset_not_found"}), 404

        if asset.is_restricted:
            grant = DownloadGrant.query.filter_by(
                asset_id=id, user_id=g.current_user.id
            ).first()
            if grant is None:
                return jsonify({"error": "forbidden", "message": "Access denied"}), 403

        return jsonify(_asset_dict(asset)), 200
