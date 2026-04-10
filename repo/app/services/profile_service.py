"""
Profile, Privacy & Visibility Controls service layer.
"""
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.profile import (
    Profile,
    VisibilityGroup,
    VisibilityGroupMember,
    ProfileFollow,
    ProfileBlock,
    ProfileHide,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_profile(profile):
    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "interest_tags": profile.interest_tags_json,
        "media_references": profile.media_references_json,
        "visibility_scope": profile.visibility_scope,
        "visibility_group_id": profile.visibility_group_id,
    }


def _stub_profile(profile):
    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
    }


# ---------------------------------------------------------------------------
# Block helpers
# ---------------------------------------------------------------------------

def is_blocked(user_a_id: int, user_b_id: int) -> bool:
    """Return True if A blocked B OR B blocked A."""
    return (
        ProfileBlock.query.filter(
            db.or_(
                db.and_(ProfileBlock.blocker_id == user_a_id, ProfileBlock.blocked_id == user_b_id),
                db.and_(ProfileBlock.blocker_id == user_b_id, ProfileBlock.blocked_id == user_a_id),
            )
        ).first()
        is not None
    )


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def get_profile(target_user_id: int, requesting_user_id: int) -> dict:
    """
    Return profile fields visible to requesting user based on visibility scope.
    - If blocked (in either direction) → raise PermissionError (403)
    - public: full profile
    - mutual_followers: mutual → full; else stub
    - custom_group: requester in group → full; else stub
    """
    if is_blocked(target_user_id, requesting_user_id):
        raise PermissionError("Access denied")

    profile = Profile.query.filter_by(user_id=target_user_id).first()
    if profile is None:
        raise LookupError("profile_not_found")

    scope = profile.visibility_scope or "public"

    if scope == "public":
        return _full_profile(profile)

    if scope == "mutual_followers":
        a_follows_b = ProfileFollow.query.filter_by(
            follower_id=requesting_user_id, followee_id=target_user_id
        ).first()
        b_follows_a = ProfileFollow.query.filter_by(
            follower_id=target_user_id, followee_id=requesting_user_id
        ).first()
        if a_follows_b and b_follows_a:
            return _full_profile(profile)
        return _stub_profile(profile)

    if scope == "custom_group":
        group_id = profile.visibility_group_id
        if group_id is not None:
            member = VisibilityGroupMember.query.filter_by(
                group_id=group_id, user_id=requesting_user_id
            ).first()
            if member:
                return _full_profile(profile)
        return _stub_profile(profile)

    # Fallback
    return _full_profile(profile)


def update_profile(user_id: int, **kwargs) -> Profile:
    """Update own profile. Validates bio max 500 chars."""
    profile = Profile.query.filter_by(user_id=user_id).first()
    if profile is None:
        raise LookupError("profile_not_found")

    bio = kwargs.get("bio")
    if bio is not None and len(bio) > 500:
        raise ValueError("bio_too_long")

    allowed = {
        "display_name", "bio", "interest_tags_json",
        "media_references_json", "visibility_scope", "visibility_group_id",
    }
    for key, value in kwargs.items():
        if key in allowed:
            setattr(profile, key, value)

    db.session.commit()
    return profile


# ---------------------------------------------------------------------------
# Visibility Groups
# ---------------------------------------------------------------------------

def create_visibility_group(owner_id: int, name: str, member_ids: list) -> VisibilityGroup:
    """Create a visibility group with the given members."""
    group = VisibilityGroup(owner_id=owner_id, name=name)
    db.session.add(group)
    db.session.flush()

    for uid in member_ids:
        member = VisibilityGroupMember(group_id=group.id, user_id=uid)
        db.session.add(member)

    db.session.commit()
    return group


def get_visibility_group(group_id: int, requesting_user_id: int = None) -> dict:
    """Return group info with members list.

    Access policy: only the group owner and current members may read the group.
    Raises PermissionError if requesting_user_id is provided and is neither
    the owner nor a member.
    """
    group = db.session.get(VisibilityGroup, group_id)
    if group is None:
        raise LookupError("group_not_found")

    if requesting_user_id is not None:
        is_owner = group.owner_id == requesting_user_id
        is_member = (
            VisibilityGroupMember.query
            .filter_by(group_id=group_id, user_id=requesting_user_id)
            .first()
        ) is not None
        if not is_owner and not is_member:
            raise PermissionError("forbidden")

    members = VisibilityGroupMember.query.filter_by(group_id=group_id).all()
    return {
        "id": group.id,
        "name": group.name,
        "owner_id": group.owner_id,
        "members": [m.user_id for m in members],
    }


def add_group_member(group_id: int, user_id: int, actor_id: int) -> VisibilityGroupMember:
    """Add a member to a visibility group. Actor must be the owner."""
    group = db.session.get(VisibilityGroup, group_id)
    if group is None:
        raise LookupError("group_not_found")
    if group.owner_id != actor_id:
        raise PermissionError("not_group_owner")
    try:
        member = VisibilityGroupMember(group_id=group_id, user_id=user_id)
        db.session.add(member)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("already_member")
    return member


def remove_group_member(group_id: int, user_id: int, actor_id: int) -> None:
    """Remove a member from a visibility group. Actor must be the owner."""
    group = db.session.get(VisibilityGroup, group_id)
    if group is None:
        raise LookupError("group_not_found")
    if group.owner_id != actor_id:
        raise PermissionError("not_group_owner")
    member = VisibilityGroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
    if member is None:
        raise LookupError("member_not_found")
    db.session.delete(member)
    db.session.commit()


# ---------------------------------------------------------------------------
# Follow / Unfollow
# ---------------------------------------------------------------------------

def follow_user(follower_id: int, followee_id: int) -> ProfileFollow:
    """Create a follow relationship. Raises PermissionError if blocked."""
    if is_blocked(follower_id, followee_id):
        raise PermissionError("Access denied")
    try:
        follow = ProfileFollow(follower_id=follower_id, followee_id=followee_id)
        db.session.add(follow)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("already_following")
    return follow


def unfollow_user(follower_id: int, followee_id: int) -> None:
    """Remove a follow relationship."""
    follow = ProfileFollow.query.filter_by(
        follower_id=follower_id, followee_id=followee_id
    ).first()
    if follow is None:
        raise LookupError("follow_not_found")
    db.session.delete(follow)
    db.session.commit()


def get_followers(user_id: int) -> list:
    """Return user_ids that follow this user."""
    follows = ProfileFollow.query.filter_by(followee_id=user_id).all()
    return [f.follower_id for f in follows]


def get_following(user_id: int) -> list:
    """Return user_ids that this user follows."""
    follows = ProfileFollow.query.filter_by(follower_id=user_id).all()
    return [f.followee_id for f in follows]


# ---------------------------------------------------------------------------
# Block / Unblock
# ---------------------------------------------------------------------------

def block_user(blocker_id: int, blocked_id: int) -> ProfileBlock:
    """Block a user. Remove any existing follow relationships in both directions."""
    # Remove follow in both directions
    for follow in ProfileFollow.query.filter(
        db.or_(
            db.and_(ProfileFollow.follower_id == blocker_id, ProfileFollow.followee_id == blocked_id),
            db.and_(ProfileFollow.follower_id == blocked_id, ProfileFollow.followee_id == blocker_id),
        )
    ).all():
        db.session.delete(follow)

    try:
        block = ProfileBlock(blocker_id=blocker_id, blocked_id=blocked_id)
        db.session.add(block)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("already_blocked")
    return block


def unblock_user(blocker_id: int, blocked_id: int) -> None:
    """Unblock a user."""
    block = ProfileBlock.query.filter_by(blocker_id=blocker_id, blocked_id=blocked_id).first()
    if block is None:
        raise LookupError("block_not_found")
    db.session.delete(block)
    db.session.commit()


# ---------------------------------------------------------------------------
# Hide
# ---------------------------------------------------------------------------

def hide_user(hider_id: int, hidden_id: int) -> ProfileHide:
    """Hide a user from feed."""
    try:
        hide = ProfileHide(hider_id=hider_id, hidden_id=hidden_id)
        db.session.add(hide)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("already_hidden")
    return hide
