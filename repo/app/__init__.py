import os
import uuid
import time
import logging
from flask import Flask, g, request
from pythonjsonlogger import jsonlogger
from logging.handlers import RotatingFileHandler

from .extensions import db, migrate, api as smorest_api, limiter
from .api.health import blp as health_blp

# ---------------------------------------------------------------------------
# Structured JSON logging setup
# ---------------------------------------------------------------------------

def setup_logging(app):
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    log_file = os.environ.get("LOG_FILE")

    formatter = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"}
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    if log_file:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        app.logger.addHandler(file_handler)

    app.logger.addHandler(console_handler)
    app.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
from .api.auth import blp as auth_blp
from .api.risk import blp as risk_blp
from .api.captcha import blp as captcha_blp
from .api.membership import blp as membership_blp
from .api.marketing import blp as marketing_blp
from .api.assets import blp as assets_blp
from .api.profiles import blp as profiles_blp
from .api.policies import blp as policies_blp
from .api.admin import blp as admin_blp
from .api.compliance import blp as compliance_blp


def create_app(config=None):
    app = Flask(__name__)

    # --- Config ---
    field_key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not field_key:
        raise RuntimeError("FIELD_ENCRYPTION_KEY environment variable is required but not set")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///data/mediavault.db"
    )
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False},
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # flask-smorest / OpenAPI config
    app.config["API_TITLE"] = "MediaVault API"
    app.config["API_VERSION"] = os.environ.get("API_VERSION", "1.0.0")
    app.config["OPENAPI_VERSION"] = "3.0.3"
    app.config["OPENAPI_URL_PREFIX"] = "/"
    app.config["OPENAPI_JSON_PATH"] = "openapi.json"
    # Disable smorest's built-in Swagger UI to avoid CDN links; we serve our own
    app.config["OPENAPI_SWAGGER_UI_PATH"] = None
    app.config["OPENAPI_SWAGGER_UI_URL"] = None

    # Security schemes in OpenAPI spec
    app.config["API_SPEC_OPTIONS"] = {
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                }
            }
        }
    }

    # Rate limiter storage (memory for simplicity / tests)
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)

    if config:
        app.config.update(config)

    # --- Extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    smorest_api.init_app(app)
    limiter.init_app(app)

    # --- Structured logging ---
    setup_logging(app)

    # --- Request lifecycle hooks for logging ---
    @app.before_request
    def inject_request_id():
        g.request_id = str(uuid.uuid4())
        g.start_time = time.time()

    @app.after_request
    def log_request(response):
        duration_ms = round((time.time() - g.get('start_time', time.time())) * 1000, 2)
        user_id = getattr(getattr(g, 'current_user', None), 'id', None)

        app.logger.info(
            "request",
            extra={
                "request_id": g.get('request_id'),
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user_id": user_id,
                "ip": request.remote_addr,
            }
        )
        return response

    # --- Import models to register with SQLAlchemy ---
    from . import models  # noqa: F401

    # --- Blueprints ---
    smorest_api.register_blueprint(health_blp)
    smorest_api.register_blueprint(auth_blp)
    smorest_api.register_blueprint(risk_blp)
    smorest_api.register_blueprint(captcha_blp)
    smorest_api.register_blueprint(membership_blp)
    smorest_api.register_blueprint(marketing_blp)
    smorest_api.register_blueprint(assets_blp)
    smorest_api.register_blueprint(profiles_blp)
    smorest_api.register_blueprint(policies_blp)
    smorest_api.register_blueprint(admin_blp)
    smorest_api.register_blueprint(compliance_blp)

    # --- After-request hook: auto-log all admin API calls ---
    @app.after_request
    def log_admin_actions(response):
        if request.path.startswith("/admin/") and hasattr(g, "current_user"):
            try:
                from app.services.audit_service import log_audit
                actor = g.current_user
                actor_role = next(
                    (r.name for r in actor.roles if r.name == "admin"),
                    (actor.roles[0].name if actor.roles else None),
                )
                log_audit(
                    actor_id=actor.id,
                    actor_role=actor_role,
                    action=f"admin_{request.method.lower()}_{request.path.strip('/').replace('/', '_')}",
                    entity_type=None,
                    entity_id=None,
                    detail={
                        "method": request.method,
                        "path": request.path,
                        "status": response.status_code,
                    },
                    ip=request.remote_addr,
                )
                db.session.commit()
            except Exception:
                pass  # Never break the response due to audit logging
        return response

    # --- Enable WAL mode for SQLite ---
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import sqlite3

    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.close()

    # --- JSON Error Handlers ---
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "bad_request", "message": str(e.description)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "unauthorized", "message": str(e.description)}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "forbidden", "message": str(e.description)}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not_found", "message": str(e.description)}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "method_not_allowed", "message": str(e.description)}), 405

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify({"error": "unprocessable_entity", "message": str(e.description)}), 422

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({"error": "too_many_requests", "message": str(e.description)}), 429

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "internal_server_error", "message": "An internal error occurred"}), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify({"error": str(e.name).lower().replace(" ", "_"), "message": str(e.description)}), e.code
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({"error": "internal_server_error", "message": "An internal error occurred"}), 500

    # --- Test error route (only in testing mode) ---
    if app.config.get("TESTING"):
        @app.route("/test-error")
        def test_error_route():
            raise Exception("Test error")

    # --- Serve Swagger UI static files from swagger-ui-bundle package ---
    import swagger_ui_bundle

    swagger_ui_dir = swagger_ui_bundle.swagger_ui_path

    @app.route("/swagger-ui-static/<path:filename>")
    def swagger_ui_static(filename):
        from flask import send_from_directory
        return send_from_directory(swagger_ui_dir, filename)

    # --- Custom /docs route serving self-hosted Swagger UI (no CDN) ---
    @app.route("/docs")
    def swagger_ui_page():
        from flask import Response
        html = """<!DOCTYPE html>
<html>
<head>
  <title>MediaVault API Docs</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" type="text/css" href="/swagger-ui-static/swagger-ui.css" >
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="/swagger-ui-static/swagger-ui-bundle.js"> </script>
  <script src="/swagger-ui-static/swagger-ui-standalone-preset.js"> </script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: '#swagger-ui',
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        layout: "StandaloneLayout"
      })
    }
  </script>
</body>
</html>"""
        return Response(html, status=200, mimetype="text/html")

    return app
