"""
Authentication decorators and helpers.
"""
import functools

from flask import request, g, jsonify

from app.services.auth_service import get_current_user
from app.models.risk import Blacklist
from datetime import datetime, timezone


def get_token_from_request() -> str | None:
    """Extract Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]
    return None


def require_auth(f):
    """
    Decorator that validates the Bearer token and sets g.current_user.

    Returns 401 JSON if the token is missing, expired, or revoked.
    Returns 403 JSON if the user is on an active blacklist.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        if not token:
            return jsonify({"error": "unauthorized", "message": "Missing or invalid Authorization header"}), 401

        try:
            user = get_current_user(token)
        except LookupError as exc:
            reason = str(exc)
            if reason == "token_expired":
                return jsonify({"error": "unauthorized", "message": "Session expired"}), 401
            if reason == "token_revoked":
                return jsonify({"error": "unauthorized", "message": "Session revoked"}), 401
            return jsonify({"error": "unauthorized", "message": "Invalid token"}), 401

        # Blacklist check - user
        now = datetime.now(timezone.utc)
        blacklisted = (
            Blacklist.query
            .filter(
                Blacklist.target_type == "user",
                Blacklist.target_id == str(user.id),
                Blacklist.start_at <= now,
                (Blacklist.end_at == None) | (Blacklist.end_at > now),  # noqa: E711
            )
            .first()
        )
        if blacklisted:
            return jsonify({"error": "forbidden", "message": "Account is blacklisted"}), 403

        # Blacklist check - IP
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
            or ""
        )
        if client_ip:
            ip_blacklisted = (
                Blacklist.query
                .filter(
                    Blacklist.target_type == "ip",
                    Blacklist.target_id == client_ip,
                    Blacklist.start_at <= now,
                    (Blacklist.end_at == None) | (Blacklist.end_at > now),  # noqa: E711
                )
                .first()
            )
            if ip_blacklisted:
                return jsonify({"error": "forbidden", "message": "IP address is blacklisted"}), 403

        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def require_auth_allow_blacklisted(f):
    """
    Variant of require_auth that validates the token but does NOT block blacklisted
    users/IPs. Use for endpoints that blacklisted subjects need to access (e.g., appeals).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        if not token:
            return jsonify({"error": "unauthorized", "message": "Missing or invalid Authorization header"}), 401

        try:
            user = get_current_user(token)
        except LookupError as exc:
            reason = str(exc)
            if reason == "token_expired":
                return jsonify({"error": "unauthorized", "message": "Session expired"}), 401
            if reason == "token_revoked":
                return jsonify({"error": "unauthorized", "message": "Session revoked"}), 401
            return jsonify({"error": "unauthorized", "message": "Invalid token"}), 401

        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def require_role(*roles):
    """
    Decorator factory that ensures g.current_user has at least one of the
    given roles. Must be applied *after* require_auth (i.e., listed *before*
    it in the decorator stack, which means it wraps the inner function first).

    Usage::

        @require_auth
        @require_role("admin")
        def my_view(): ...

    Or more naturally with MethodView dispatch, apply both in the method body
    or chain as::

        @blp.route("/...")
        class MyView(MethodView):
            @require_auth
            @require_role("admin")
            def post(self, ...):
                ...
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is None:
                return jsonify({"error": "unauthorized", "message": "Authentication required"}), 401
            user_role_names = {r.name for r in user.roles}
            if not user_role_names.intersection(roles):
                return jsonify({"error": "forbidden", "message": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
