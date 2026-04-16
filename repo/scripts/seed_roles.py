"""
One-time bootstrap: assign admin/moderator/reviewer roles to the
users with the matching usernames.

Usage (inside the running container):
    python -m scripts.seed_roles

Idempotent — safe to re-run; skips assignments that already exist.
"""
from app import create_app
from app.extensions import db
from app.models.auth import User, Role


ROLE_MAP = {
    "admin":     "admin",
    "moderator": "moderator",
    "reviewer":  "reviewer",
}


def seed():
    app = create_app()
    with app.app_context():
        for username, role_name in ROLE_MAP.items():
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name)
                db.session.add(role)
                db.session.flush()

            user = User.query.filter_by(username=username).first()
            if user and role not in user.roles:
                user.roles.append(role)
                print(f"  {username} -> {role_name}")
            elif not user:
                print(f"  skipped {username} (user not registered)")
            else:
                print(f"  {username} already has {role_name}")

        db.session.commit()
        print("Done.")


if __name__ == "__main__":
    seed()
