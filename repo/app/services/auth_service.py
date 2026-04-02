"""
Authentication & account security business logic.
"""
import secrets
from datetime import datetime, timezone, timedelta

from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.auth import User, Role, UserRole, Session, LoginAttempt
from app.models.profile import Profile
from app.models.membership import Membership
from app.models.risk import Blacklist
from app.services.audit_service import log_audit
from app.services.master_record_service import create_master_record

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12, deprecated="auto")

LOCKOUT_ATTEMPTS = 5
LOCKOUT_WINDOW_MINUTES = 15
LOCKOUT_DURATION_MINUTES = 30
SESSION_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def _count_recent_failures(user_id: int, now: datetime) -> int:
    """Count failed login attempts in the rolling 15-minute window."""
    window_start = now - timedelta(minutes=LOCKOUT_WINDOW_MINUTES)
    return (
        LoginAttempt.query
        .filter(
            LoginAttempt.user_id == user_id,
            LoginAttempt.success == False,  # noqa: E712
            LoginAttempt.attempted_at >= window_start,
        )
        .count()
    )


def _record_login_attempt(user_id, ip: str, success: bool) -> None:
    attempt = LoginAttempt(
        user_id=user_id,
        ip=ip,
        attempted_at=datetime.now(timezone.utc),
        success=success,
    )
    db.session.add(attempt)


def _is_user_blacklisted(user_id: int) -> bool:
    now = datetime.now(timezone.utc)
    return (
        Blacklist.query
        .filter(
            Blacklist.target_type == "user",
            Blacklist.target_id == str(user_id),
            Blacklist.start_at <= now,
            db.or_(Blacklist.end_at == None, Blacklist.end_at > now),  # noqa: E711
        )
        .first() is not None
    )


def _get_or_create_role(name: str) -> Role:
    role = Role.query.filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        db.session.add(role)
        db.session.flush()
    return role


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def register_user(username: str, email: str, password: str) -> User:
    """
    Register a new user.

    Creates User, Profile, Membership, and MasterRecord in one transaction.
    Assigns the "user" role.

    :raises ValueError: on duplicate username / email (caller should map to 409)
    """
    password_hash = _hash_password(password)

    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(user)
    try:
        db.session.flush()  # catch unique violations early
    except IntegrityError:
        db.session.rollback()
        raise ValueError("username_or_email_taken")

    # Assign "user" role
    user_role = _get_or_create_role("user")
    db.session.add(UserRole(user_id=user.id, role_id=user_role.id))

    # Create profile
    profile = Profile(
        user_id=user.id,
        display_name=username,
        visibility_scope="public",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(profile)

    # Create membership (no tier yet)
    membership = Membership(
        user_id=user.id,
        points_balance=0,
        stored_value_balance=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(membership)

    db.session.flush()

    # Create master record for this user
    create_master_record(
        entity_type="user",
        entity_id=user.id,
        initial_status="active",
        created_by=user.id,
    )

    db.session.commit()
    return user


def login_user(username: str, password: str, ip: str) -> Session:
    """
    Authenticate a user and create a session.

    :raises LookupError:    if the username does not exist
    :raises PermissionError: if the account is locked
    :raises ValueError:     if the password is wrong
    :returns:               a valid Session object
    """
    now = datetime.now(timezone.utc)

    user = User.query.filter_by(username=username).first()
    if user is None:
        # Don't reveal whether the username exists
        raise LookupError("invalid_credentials")

    # Check if user is anonymized
    if user.status == 'anonymized':
        raise ValueError("account_anonymized")

    # Check lock (DB-level locked_until field)
    if user.locked_until is not None:
        locked_until_aware = user.locked_until
        if locked_until_aware.tzinfo is None:
            locked_until_aware = locked_until_aware.replace(tzinfo=timezone.utc)
        if locked_until_aware > now:
            log_audit(
                actor_id=user.id,
                actor_role=None,
                action="login_failure",
                entity_type="user",
                entity_id=user.id,
                detail={"reason": "account_locked", "ip": ip},
                ip=ip,
            )
            db.session.commit()
            raise PermissionError(f"account_locked:{user.locked_until.isoformat()}")

    # Count recent failures (rolling window) BEFORE verifying password
    recent_failures = _count_recent_failures(user.id, now)

    # Verify password
    if not _verify_password(password, user.password_hash):
        _record_login_attempt(user.id, ip, success=False)
        db.session.flush()

        # Re-count after recording this failure
        new_failure_count = _count_recent_failures(user.id, now)

        log_audit(
            actor_id=user.id,
            actor_role=None,
            action="login_failure",
            entity_type="user",
            entity_id=user.id,
            detail={"reason": "wrong_password", "ip": ip, "failure_count": new_failure_count},
            ip=ip,
        )

        if new_failure_count >= LOCKOUT_ATTEMPTS:
            locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            user.locked_until = locked_until
            user.status = "locked"
            log_audit(
                actor_id=user.id,
                actor_role=None,
                action="account_locked",
                entity_type="user",
                entity_id=user.id,
                detail={"locked_until": locked_until.isoformat(), "ip": ip},
                ip=ip,
            )
            db.session.commit()
            raise PermissionError(f"account_locked:{locked_until.isoformat()}")

        db.session.commit()
        raise ValueError("invalid_credentials")

    # Password is correct — clear any stale lock and create session
    if user.locked_until is not None:
        user.locked_until = None
        user.status = "active"

    _record_login_attempt(user.id, ip, success=True)

    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    session = Session(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
        created_at=now,
    )
    db.session.add(session)

    log_audit(
        actor_id=user.id,
        actor_role=None,
        action="login_success",
        entity_type="user",
        entity_id=user.id,
        detail={"ip": ip},
        ip=ip,
    )

    db.session.commit()
    return session


def logout_user(token: str) -> None:
    """
    Revoke the session identified by *token*.

    :raises LookupError: if the token is not found or already revoked
    """
    session = Session.query.filter_by(token=token).first()
    if session is None or session.revoked_at is not None:
        raise LookupError("invalid_token")

    session.revoked_at = datetime.now(timezone.utc)
    db.session.commit()


def refresh_session(token: str) -> Session:
    """
    Create a new session token and revoke the old one.

    :raises LookupError:  if token not found, revoked, or expired
    :returns:             the new Session
    """
    now = datetime.now(timezone.utc)
    old_session = Session.query.filter_by(token=token).first()
    if old_session is None:
        raise LookupError("invalid_token")
    if old_session.revoked_at is not None:
        raise LookupError("token_revoked")

    expires_at = old_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise LookupError("token_expired")

    # Revoke old token
    old_session.revoked_at = now

    # Create new session
    new_token = secrets.token_urlsafe(32)
    new_expires = now + timedelta(hours=SESSION_TTL_HOURS)
    new_session = Session(
        user_id=old_session.user_id,
        token=new_token,
        expires_at=new_expires,
        created_at=now,
    )
    db.session.add(new_session)
    db.session.commit()
    return new_session


def get_current_user(token: str) -> User:
    """
    Return the User for a valid, non-expired, non-revoked session token.

    :raises LookupError: for any invalid condition
    """
    now = datetime.now(timezone.utc)
    session = Session.query.filter_by(token=token).first()
    if session is None:
        raise LookupError("invalid_token")
    if session.revoked_at is not None:
        raise LookupError("token_revoked")

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise LookupError("token_expired")

    user = db.session.get(User, session.user_id)
    if user is None:
        raise LookupError("user_not_found")

    return user


def unlock_user(user_id: int, admin_id: int) -> User:
    """
    Clear the lockout on a user (admin action).

    :raises LookupError: if the user does not exist
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise LookupError("user_not_found")

    user.locked_until = None
    user.status = "active"

    log_audit(
        actor_id=admin_id,
        actor_role="admin",
        action="account_unlocked",
        entity_type="user",
        entity_id=user_id,
        detail={"unlocked_by": admin_id},
        ip=None,
    )

    db.session.commit()
    return user
