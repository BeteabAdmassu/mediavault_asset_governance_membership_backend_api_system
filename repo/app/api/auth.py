"""
Authentication API blueprint.
"""
import flask_smorest
import marshmallow as ma
from marshmallow import validate
from flask import request, g, jsonify
from flask.views import MethodView
from werkzeug.exceptions import abort as http_abort

from flask_limiter.util import get_remote_address

from app.utils.auth_utils import require_auth, require_role
from app.utils.captcha_utils import require_captcha_token
from app.extensions import limiter


def _get_user_key():
    """Rate-limit key: user-id extracted from Bearer token, else remote IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token_str = auth_header[7:]
        # Try to resolve user id from session token
        try:
            from app.models.auth import Session
            session = Session.query.filter_by(token=token_str, is_active=True).first()
            if session:
                return f"user:{session.user_id}"
        except Exception:
            pass
    return get_remote_address()

blp = flask_smorest.Blueprint(
    "auth",
    "auth",
    url_prefix="/auth",
    description="Authentication & account security",
)


def _abort(status_code, message):
    """Return a JSON error response (bypasses smorest schema serialization)."""
    from flask import current_app
    resp = jsonify({"error": str(status_code), "message": message})
    resp.status_code = status_code
    # Raise an HTTPException so Flask's error-handler chain sees it.
    http_abort(resp)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterSchema(ma.Schema):
    username = ma.fields.Str(
        required=True,
        validate=validate.Regexp(
            r"^[a-zA-Z0-9_]{3,64}$",
            error="Username must be 3-64 characters and contain only letters, digits, or underscores.",
        ),
    )
    email = ma.fields.Email(required=True)
    password = ma.fields.Str(
        required=True,
        validate=validate.Length(min=12, error="Password must be at least 12 characters."),
        load_only=True,
    )


class LoginSchema(ma.Schema):
    username = ma.fields.Str(required=True)
    password = ma.fields.Str(required=True, load_only=True)


class TokenResponseSchema(ma.Schema):
    token = ma.fields.Str()
    expires_at = ma.fields.Str()
    user_id = ma.fields.Int()


class RegisterResponseSchema(ma.Schema):
    user_id = ma.fields.Int()
    username = ma.fields.Str()
    email = ma.fields.Str()


class MeResponseSchema(ma.Schema):
    user_id = ma.fields.Int()
    username = ma.fields.Str()
    email = ma.fields.Str()
    status = ma.fields.Str()
    roles = ma.fields.List(ma.fields.Str())


class MessageSchema(ma.Schema):
    message = ma.fields.Str()
    user_id = ma.fields.Int(load_default=None, dump_default=None)
    locked_until = ma.fields.Str(load_default=None, dump_default=None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blp.route("/register")
class RegisterView(MethodView):
    @blp.doc(
        summary="Register a new user",
        description=(
            "Creates a new user account along with a Profile, Membership, and MasterRecord. "
            "Returns 409 on duplicate username or email, 422 on validation failure. "
            "Requires a valid X-Captcha-Token header (skipped in TESTING mode)."
        ),
    )
    @blp.arguments(RegisterSchema)
    @blp.response(201, RegisterResponseSchema)
    @limiter.limit("60/hour")
    @require_captcha_token
    def post(self, data):
        from app.services.auth_service import register_user

        try:
            user = register_user(
                username=data["username"],
                email=data["email"],
                password=data["password"],
            )
        except ValueError as exc:
            if "taken" in str(exc):
                return jsonify({"error": "conflict", "message": "Username or email already in use."}), 409
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422

        return {"user_id": user.id, "username": user.username, "email": user.email}, 201


@blp.route("/login")
class LoginView(MethodView):
    @blp.doc(
        summary="Login",
        description=(
            "Authenticate with username and password. "
            "Returns 401 on wrong password, 423 when the account is locked."
        ),
    )
    @blp.arguments(LoginSchema)
    @blp.response(200, TokenResponseSchema)
    @limiter.limit("60/hour")
    def post(self, data):
        from app.services.auth_service import login_user

        ip = request.remote_addr or "unknown"

        try:
            session = login_user(
                username=data["username"],
                password=data["password"],
                ip=ip,
            )
        except ValueError as exc:
            if "account_anonymized" in str(exc):
                return jsonify({"error": "account_anonymized", "message": "This account has been deleted."}), 401
            return jsonify({"error": "unauthorized", "message": "Invalid username or password."}), 401
        except LookupError:
            return jsonify({"error": "unauthorized", "message": "Invalid username or password."}), 401
        except PermissionError as exc:
            msg = str(exc)
            if msg.startswith("account_locked:"):
                locked_until = msg.split(":", 1)[1]
                return jsonify({
                    "error": "locked",
                    "message": "Account is locked due to too many failed login attempts.",
                    "locked_until": locked_until,
                }), 423
            return jsonify({"error": "forbidden", "message": "Account access denied."}), 403

        return {
            "token": session.token,
            "expires_at": session.expires_at.isoformat(),
            "user_id": session.user_id,
        }


@blp.route("/logout")
class LogoutView(MethodView):
    @blp.doc(
        summary="Logout",
        description="Revoke the current session token.",
        security=[{"BearerAuth": []}],
    )
    @blp.response(200, MessageSchema)
    @require_auth
    def post(self):
        from app.services.auth_service import logout_user
        from app.utils.auth_utils import get_token_from_request

        token = get_token_from_request()
        try:
            logout_user(token)
        except LookupError:
            return jsonify({"error": "unauthorized", "message": "Invalid or already-revoked token."}), 401

        return {"message": "Logged out successfully."}


@blp.route("/refresh")
class RefreshView(MethodView):
    @blp.doc(
        summary="Refresh session token",
        description="Exchange a valid token for a new one. The old token is revoked.",
        security=[{"BearerAuth": []}],
    )
    @blp.response(200, TokenResponseSchema)
    @require_auth
    def post(self):
        from app.services.auth_service import refresh_session
        from app.utils.auth_utils import get_token_from_request

        token = get_token_from_request()
        try:
            new_session = refresh_session(token)
        except LookupError as exc:
            return jsonify({"error": "unauthorized", "message": f"Token error: {exc}"}), 401

        return {
            "token": new_session.token,
            "expires_at": new_session.expires_at.isoformat(),
            "user_id": new_session.user_id,
        }


@blp.route("/me")
class MeView(MethodView):
    @blp.doc(
        summary="Get current user",
        description="Returns details of the authenticated user.",
        security=[{"BearerAuth": []}],
    )
    @blp.response(200, MeResponseSchema)
    @require_auth
    @limiter.limit("300/minute", key_func=_get_user_key)
    def get(self):
        user = g.current_user
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "status": user.status,
            "roles": [r.name for r in user.roles],
        }


@blp.route("/unlock/<int:user_id>")
class UnlockView(MethodView):
    @blp.doc(
        summary="Unlock a user account (admin only)",
        description="Clear the lockout on a user account. Requires admin role.",
        security=[{"BearerAuth": []}],
    )
    @blp.response(200, MessageSchema)
    @require_auth
    @require_role("admin")
    def post(self, user_id):
        from app.services.auth_service import unlock_user

        try:
            user = unlock_user(user_id=user_id, admin_id=g.current_user.id)
        except LookupError:
            return jsonify({"error": "not_found", "message": "User not found."}), 404

        return {"message": f"User {user.username} has been unlocked.", "user_id": user.id}
