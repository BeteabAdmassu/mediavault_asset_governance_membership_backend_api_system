import flask_smorest
from flask import jsonify
from flask.views import MethodView
import marshmallow as ma

blp = flask_smorest.Blueprint("health", "health", url_prefix="/", description="Health check")

class HealthResponseSchema(ma.Schema):
    status = ma.fields.Str()
    db = ma.fields.Str()

@blp.route("/healthz")
class HealthView(MethodView):
    @blp.response(200, HealthResponseSchema)
    @blp.doc(summary="Health check", description="Returns service health status")
    def get(self):
        from app.extensions import db
        from sqlalchemy import text
        try:
            db.session.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception:
            db_status = "error"

        response_data = {"status": "ok", "db": db_status}
        if db_status == "error":
            return jsonify(response_data), 503
        return response_data
