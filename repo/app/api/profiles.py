"""
Profile, Privacy & Visibility Controls API blueprint.
"""
import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role

blp = flask_smorest.Blueprint(
    "profiles",
    "profiles",
    url_prefix="/profiles",
    description="Profile management, visibility controls, follows, blocks, and hides",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProfileUpdateSchema(ma.Schema):
    display_name = ma.fields.Str(allow_none=True)
    bio = ma.fields.Str(allow_none=True)
    interest_tags_json = ma.fields.Str(allow_none=True)
    media_references_json = ma.fields.Str(allow_none=True)
    visibility_scope = ma.fields.Str(allow_none=True)
    visibility_group_id = ma.fields.Int(allow_none=True)


class VisibilityGroupCreateSchema(ma.Schema):
    name = ma.fields.Str(required=True)
    member_ids = ma.fields.List(ma.fields.Int(), load_default=list)


class AddMemberSchema(ma.Schema):
    user_id = ma.fields.Int(required=True)


# ---------------------------------------------------------------------------
# Profile routes
# ---------------------------------------------------------------------------

@blp.route("/<int:user_id>")
class ProfileView(MethodView):
    @blp.doc(summary="Get a user's profile (visibility-filtered)", security=[{"BearerAuth": []}])
    @require_auth
    def get(self, user_id):
        from app.services.profile_service import get_profile
        try:
            data = get_profile(
                target_user_id=user_id,
                requesting_user_id=g.current_user.id,
            )
        except PermissionError:
            return jsonify({"error": "forbidden", "message": "Access denied"}), 403
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(data), 200


@blp.route("/me")
class OwnProfileView(MethodView):
    @blp.doc(summary="Update own profile", security=[{"BearerAuth": []}])
    @blp.arguments(ProfileUpdateSchema)
    @require_auth
    def patch(self, data):
        from app.services.profile_service import update_profile
        try:
            profile = update_profile(user_id=g.current_user.id, **data)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify({
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "bio": profile.bio,
            "visibility_scope": profile.visibility_scope,
            "visibility_group_id": profile.visibility_group_id,
        }), 200


# ---------------------------------------------------------------------------
# Followers / Following
# ---------------------------------------------------------------------------

@blp.route("/me/followers")
class FollowersView(MethodView):
    @blp.doc(summary="Get followers of current user", security=[{"BearerAuth": []}])
    @require_auth
    def get(self):
        from app.services.profile_service import get_followers
        followers = get_followers(g.current_user.id)
        return jsonify({"followers": followers}), 200


@blp.route("/me/following")
class FollowingView(MethodView):
    @blp.doc(summary="Get users that current user follows", security=[{"BearerAuth": []}])
    @require_auth
    def get(self):
        from app.services.profile_service import get_following
        following = get_following(g.current_user.id)
        return jsonify({"following": following}), 200


# ---------------------------------------------------------------------------
# Follow / Unfollow
# ---------------------------------------------------------------------------

@blp.route("/<int:user_id>/follow")
class FollowView(MethodView):
    @blp.doc(summary="Follow a user", security=[{"BearerAuth": []}])
    @require_auth
    def post(self, user_id):
        from app.services.profile_service import follow_user
        try:
            follow_user(follower_id=g.current_user.id, followee_id=user_id)
        except PermissionError:
            return jsonify({"error": "forbidden", "message": "Access denied"}), 403
        except ValueError as exc:
            return jsonify({"error": "conflict", "message": str(exc)}), 409
        return jsonify({"message": "followed"}), 201

    @blp.doc(summary="Unfollow a user", security=[{"BearerAuth": []}])
    @require_auth
    def delete(self, user_id):
        from app.services.profile_service import unfollow_user
        try:
            unfollow_user(follower_id=g.current_user.id, followee_id=user_id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"message": "unfollowed"}), 200


# ---------------------------------------------------------------------------
# Block / Unblock
# ---------------------------------------------------------------------------

@blp.route("/<int:user_id>/block")
class BlockView(MethodView):
    @blp.doc(summary="Block a user", security=[{"BearerAuth": []}])
    @require_auth
    def post(self, user_id):
        from app.services.profile_service import block_user
        try:
            block_user(blocker_id=g.current_user.id, blocked_id=user_id)
        except ValueError as exc:
            return jsonify({"error": "conflict", "message": str(exc)}), 409
        return jsonify({"message": "blocked"}), 201

    @blp.doc(summary="Unblock a user", security=[{"BearerAuth": []}])
    @require_auth
    def delete(self, user_id):
        from app.services.profile_service import unblock_user
        try:
            unblock_user(blocker_id=g.current_user.id, blocked_id=user_id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"message": "unblocked"}), 200


# ---------------------------------------------------------------------------
# Hide
# ---------------------------------------------------------------------------

@blp.route("/<int:user_id>/hide")
class HideView(MethodView):
    @blp.doc(summary="Hide a user from feed", security=[{"BearerAuth": []}])
    @require_auth
    def post(self, user_id):
        from app.services.profile_service import hide_user
        try:
            hide_user(hider_id=g.current_user.id, hidden_id=user_id)
        except ValueError as exc:
            return jsonify({"error": "conflict", "message": str(exc)}), 409
        return jsonify({"message": "hidden"}), 201


# ---------------------------------------------------------------------------
# Visibility Groups
# ---------------------------------------------------------------------------

@blp.route("/groups")
class VisibilityGroupsView(MethodView):
    @blp.doc(summary="Create a visibility group", security=[{"BearerAuth": []}])
    @blp.arguments(VisibilityGroupCreateSchema)
    @require_auth
    def post(self, data):
        from app.services.profile_service import create_visibility_group
        group = create_visibility_group(
            owner_id=g.current_user.id,
            name=data["name"],
            member_ids=data.get("member_ids", []),
        )
        return jsonify({"id": group.id, "name": group.name, "owner_id": group.owner_id}), 201


@blp.route("/groups/<int:id>")
class VisibilityGroupDetailView(MethodView):
    @blp.doc(summary="Get a visibility group with members", security=[{"BearerAuth": []}])
    @require_auth
    def get(self, id):
        from app.services.profile_service import get_visibility_group
        try:
            data = get_visibility_group(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(data), 200


@blp.route("/groups/<int:id>/members")
class VisibilityGroupMembersView(MethodView):
    @blp.doc(summary="Add a member to a visibility group", security=[{"BearerAuth": []}])
    @blp.arguments(AddMemberSchema)
    @require_auth
    def post(self, data, id):
        from app.services.profile_service import add_group_member
        try:
            add_group_member(group_id=id, user_id=data["user_id"], actor_id=g.current_user.id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"error": "forbidden", "message": str(exc)}), 403
        except ValueError as exc:
            return jsonify({"error": "conflict", "message": str(exc)}), 409
        return jsonify({"message": "member added"}), 201


@blp.route("/groups/<int:id>/members/<int:user_id>")
class VisibilityGroupMemberDetailView(MethodView):
    @blp.doc(summary="Remove a member from a visibility group", security=[{"BearerAuth": []}])
    @require_auth
    def delete(self, id, user_id):
        from app.services.profile_service import remove_group_member
        try:
            remove_group_member(group_id=id, user_id=user_id, actor_id=g.current_user.id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"error": "forbidden", "message": str(exc)}), 403
        return jsonify({"message": "member removed"}), 200
