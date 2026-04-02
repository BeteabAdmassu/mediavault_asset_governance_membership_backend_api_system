"""
CAPTCHA utility: decorator / helper that validates and consumes a captcha token
from the X-Captcha-Token request header.
"""
import functools
from flask import request, current_app
from werkzeug.exceptions import abort


def require_captcha_token(f):
    """Decorator that enforces a valid, unused captcha token.

    Reads the ``X-Captcha-Token`` header, validates it, and consumes it.
    Aborts with 400 if the header is missing, the token is invalid, already
    used, or expired.

    In TESTING mode (``app.config['TESTING'] is True``) the check is skipped
    so that existing test fixtures that create users directly can keep working.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if current_app.config.get("TESTING"):
            return f(*args, **kwargs)

        token_id = request.headers.get("X-Captcha-Token")
        if not token_id:
            abort(400, description="X-Captcha-Token header is required.")

        from app.services.captcha_service import consume_captcha_token
        try:
            consume_captcha_token(token_id)
        except ValueError:
            abort(400, description="Captcha token is invalid, expired, or already used.")

        return f(*args, **kwargs)

    return wrapper
