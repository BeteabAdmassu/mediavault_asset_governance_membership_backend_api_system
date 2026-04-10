"""
Compliance API blueprint: data export and deletion requests.
"""
import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request, send_file
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role

blp = flask_smorest.Blueprint(
    "compliance",
    "compliance",
    url_prefix="/compliance",
    description="Data export and deletion compliance (GDPR)",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExportRequestResponseSchema(ma.Schema):
    request_id = ma.fields.Int()
    status = ma.fields.Str()


class DeletionRequestResponseSchema(ma.Schema):
    request_id = ma.fields.Int()
    status = ma.fields.Str()


class ProcessResponseSchema(ma.Schema):
    request_id = ma.fields.Int()
    status = ma.fields.Str()


class DataRequestSchema(ma.Schema):
    id = ma.fields.Int()
    user_id = ma.fields.Int()
    type = ma.fields.Str()
    status = ma.fields.Str()
    requested_at = ma.fields.Str()
    completed_at = ma.fields.Str(allow_none=True)
    notes = ma.fields.Str(allow_none=True)


class PaginatedDataRequestsSchema(ma.Schema):
    items = ma.fields.List(ma.fields.Nested(DataRequestSchema))
    total = ma.fields.Int()
    page = ma.fields.Int()
    per_page = ma.fields.Int()
    pages = ma.fields.Int()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _req_dict(req):
    return {
        "id": req.id,
        "user_id": req.user_id,
        "type": req.type,
        "status": req.status,
        "requested_at": req.requested_at.isoformat() if req.requested_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "notes": req.notes,
    }


# ---------------------------------------------------------------------------
# Export Request Routes
# ---------------------------------------------------------------------------

@blp.route("/export-request")
class ExportRequestView(MethodView):
    @blp.doc(
        summary="Create an export request (authenticated)",
        description="Create a data export request for the authenticated user.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def post(self):
        from app.services.compliance_service import create_export_request

        user = g.current_user
        result = create_export_request(user_id=user.id)
        return jsonify(result), 201


@blp.route("/export-request/<int:id>/process")
class ExportProcessView(MethodView):
    @blp.doc(
        summary="Process an export request (admin only)",
        description="Admin: generate the export file for a pending export request.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def post(self, id):
        from app.services.compliance_service import process_export

        try:
            result = process_export(request_id=id, processed_by=g.current_user.id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404

        return jsonify({"request_id": id, "status": result["status"]}), 200


@blp.route("/export-request/<int:id>/download")
class ExportDownloadView(MethodView):
    @blp.doc(
        summary="Download an export file (owner or admin)",
        description="Download the generated export JSON file.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def get(self, id):
        from app.services.compliance_service import get_export_file

        user = g.current_user
        is_admin = any(r.name == "admin" for r in user.roles)

        try:
            file_path = get_export_file(
                request_id=id,
                requesting_user_id=user.id,
                is_admin=is_admin,
            )
        except PermissionError:
            return jsonify({"error": "forbidden", "message": "Access denied"}), 403
        except LookupError:
            return jsonify({"error": "not_found", "message": "Export not found or not complete"}), 404

        return send_file(
            file_path,
            mimetype='application/json',
            as_attachment=True,
            download_name=f"export_{id}.json",
        )


# ---------------------------------------------------------------------------
# Deletion Request Routes
# ---------------------------------------------------------------------------

@blp.route("/deletion-request")
class DeletionRequestView(MethodView):
    @blp.doc(
        summary="Create a deletion request (authenticated)",
        description="Create a deletion request for the authenticated user's own account.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def post(self):
        from app.services.compliance_service import create_deletion_request

        user = g.current_user
        result = create_deletion_request(user_id=user.id)
        return jsonify(result), 201


@blp.route("/deletion-request/<int:id>/process")
class DeletionProcessView(MethodView):
    @blp.doc(
        summary="Process a deletion request (admin only)",
        description="Admin: anonymize the user associated with the deletion request.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def post(self, id):
        from app.services.compliance_service import process_deletion

        try:
            result = process_deletion(request_id=id, processed_by=g.current_user.id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except Exception:
            from flask import current_app
            current_app.logger.exception(
                "Unexpected error processing deletion request %s", id
            )
            return jsonify({
                "error": "internal_server_error",
                "message": "An unexpected error occurred. Please contact support.",
            }), 500

        return jsonify({"request_id": id, "status": result["status"]}), 200


# ---------------------------------------------------------------------------
# Admin: List all data requests
# ---------------------------------------------------------------------------

@blp.route("/requests")
class DataRequestsView(MethodView):
    @blp.doc(
        summary="List all data requests (admin only)",
        description="Admin: paginated list of all export and deletion requests.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.compliance_service import get_data_requests

        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        type_filter = request.args.get("type")
        status_filter = request.args.get("status")

        pagination = get_data_requests(
            page=page,
            per_page=per_page,
            type=type_filter,
            status=status_filter,
        )

        return jsonify({
            "items": [_req_dict(r) for r in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200
