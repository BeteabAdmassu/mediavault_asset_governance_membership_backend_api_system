"""
CAPTCHA API blueprint.
"""
import flask_smorest
import marshmallow as ma
from flask import jsonify
from flask.views import MethodView

from app.extensions import limiter

blp = flask_smorest.Blueprint(
    "captcha",
    "captcha",
    url_prefix="/captcha",
    description="Offline CAPTCHA challenge & verification",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChallengeResponseSchema(ma.Schema):
    challenge_id = ma.fields.Int()
    question = ma.fields.Str()


class VerifySchema(ma.Schema):
    challenge_id = ma.fields.Int(required=True)
    answer = ma.fields.Str(required=True)


class VerifyResponseSchema(ma.Schema):
    valid = ma.fields.Bool()
    token = ma.fields.Str(load_default=None, dump_default=None)
    error = ma.fields.Str(load_default=None, dump_default=None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blp.route("/challenge")
class ChallengeView(MethodView):
    @blp.doc(
        summary="Get a CAPTCHA challenge",
        description="Returns a challenge_id and a question the user must answer.",
    )
    @blp.response(200, ChallengeResponseSchema)
    @limiter.limit("30/minute")
    def get(self):
        from app.services.captcha_service import create_challenge
        return create_challenge()


@blp.route("/verify")
class VerifyView(MethodView):
    @blp.doc(
        summary="Verify a CAPTCHA answer",
        description=(
            "Submit an answer for a challenge. Returns valid=true and a one-time token "
            "on success. Returns an error code if expired or max attempts exceeded."
        ),
    )
    @blp.arguments(VerifySchema)
    @blp.response(200, VerifyResponseSchema)
    @limiter.limit("30/minute")
    def post(self, data):
        from app.services.captcha_service import verify_challenge

        result = verify_challenge(data["challenge_id"], data["answer"])

        error_code = result.get("error")
        if error_code == "challenge_expired":
            return jsonify({"error": "challenge_expired", "message": "Challenge has expired."}), 400
        if error_code == "max_attempts_exceeded":
            return jsonify({"error": "max_attempts_exceeded", "message": "Too many attempts."}), 400
        if error_code == "challenge_not_found":
            return jsonify({"error": "not_found", "message": "Challenge not found."}), 404

        return result
