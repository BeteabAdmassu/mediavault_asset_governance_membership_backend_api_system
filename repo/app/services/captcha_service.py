"""
CAPTCHA service: create challenges, verify answers, manage tokens.
"""
import json
import random
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.extensions import db
from app.models.captcha import CaptchaChallenge, CaptchaToken

# ---------------------------------------------------------------------------
# Load puzzles from JSON once at import time
# ---------------------------------------------------------------------------

_PUZZLES_PATH = Path(__file__).parent.parent / "data" / "captcha_puzzles.json"

with open(_PUZZLES_PATH, "r", encoding="utf-8") as _f:
    _PUZZLES: list[dict] = json.load(_f)

_PUZZLES_BY_KEY: dict[str, dict] = {p["key"]: p for p in _PUZZLES}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_challenge() -> dict:
    """Pick a random puzzle and persist a CaptchaChallenge row.

    Returns:
        {"challenge_id": int, "question": str}
    """
    puzzle = random.choice(_PUZZLES)

    challenge = CaptchaChallenge(
        question_key=puzzle["key"],
        answer_hash=_sha256(puzzle["answer"].strip().lower()),
        expires_at=_now() + timedelta(minutes=5),
        attempts=0,
    )
    db.session.add(challenge)
    db.session.commit()

    return {"challenge_id": challenge.id, "question": puzzle["question"]}


def verify_challenge(challenge_id: int, answer: str) -> dict:
    """Verify a user's answer to a CAPTCHA challenge.

    Returns a dict with keys:
      - ``valid`` (bool)
      - ``token`` (str UUID) – only when valid is True
      - ``error`` (str)     – only on terminal errors

    Error codes:
      - ``challenge_not_found``
      - ``challenge_expired``
      - ``max_attempts_exceeded``
    """
    challenge = db.session.get(CaptchaChallenge, challenge_id)
    if challenge is None:
        return {"valid": False, "error": "challenge_not_found"}

    now = _now()

    # Normalise stored expires_at to timezone-aware for comparison
    expires_at = challenge.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return {"valid": False, "error": "challenge_expired"}

    if challenge.attempts >= 3:
        return {"valid": False, "error": "max_attempts_exceeded"}

    # Increment attempts before checking correctness (counts even wrong guesses)
    challenge.attempts += 1
    db.session.commit()

    answer_hash = _sha256(answer.strip().lower())
    if answer_hash != challenge.answer_hash:
        return {"valid": False}

    # Correct – mark used and issue a token
    challenge.used_at = now
    token = CaptchaToken(
        id=str(uuid.uuid4()),
        challenge_id=challenge.id,
        expires_at=now + timedelta(minutes=5),
    )
    db.session.add(token)
    db.session.commit()

    return {"valid": True, "token": token.id}


def validate_captcha_token(token_id: str):
    """Return the CaptchaToken if it exists, is not used, and is not expired.

    Returns None if the token is invalid / expired / already used.
    """
    if not token_id:
        return None

    token = db.session.get(CaptchaToken, token_id)
    if token is None:
        return None

    if token.used_at is not None:
        return None

    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if _now() > expires_at:
        return None

    return token


def consume_captcha_token(token_id: str) -> CaptchaToken:
    """Mark a captcha token as used.

    Raises:
        ValueError: if the token is missing, already used, or expired.
    """
    token = validate_captcha_token(token_id)
    if token is None:
        raise ValueError("captcha_token_invalid_or_expired")

    token.used_at = _now()
    db.session.commit()
    return token
