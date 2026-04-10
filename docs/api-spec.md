# API Contract Reference — MediaVault Backend

All endpoints return JSON. Auth endpoints use bearer tokens:
`Authorization: Bearer <token>`

Error envelope: `{"error": "<code>", "message": "<human text>"}`.

---

## Authentication (`/auth`)

### POST /auth/register
Create a new account. Requires a valid `X-Captcha-Token` header (bypassed in TESTING mode).

| | |
|---|---|
| **Auth** | None |
| **Rate limit** | 60/hour (IP) |
| **Request** | `username` (str, 3–64 alnum+_), `email`, `password` (≥12 chars) |
| **201** | `{user_id, username, email}` |
| **400** | `captcha_required` — token missing after failed login; `captcha_invalid` — bad token |
| **409** | `conflict` — username or email already taken |
| **422** | `unprocessable_entity` — validation error (password too short, bad username) |
| **429** | Rate limit exceeded |

### POST /auth/login
Authenticate and receive a session token.

| | |
|---|---|
| **Auth** | None |
| **Rate limit** | 60/hour (IP) |
| **Request** | `username`, `password` |
| **200** | `{token, expires_at, user_id}` |
| **401** | `unauthorized` — wrong credentials or anonymized account |
| **423** | `locked` — account locked; includes `locked_until` timestamp |
| **429** | Rate limit exceeded |

### POST /auth/logout
Revoke the current session.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **Rate limit** | 30/minute (user) |
| **200** | `{message}` |
| **401** | Invalid or already-revoked token |

### POST /auth/refresh
Exchange a valid token for a new one (old token revoked).

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **Rate limit** | 30/minute (user) |
| **200** | `{token, expires_at, user_id}` |
| **401** | Token invalid, revoked, or expired |
| **429** | Rate limit exceeded |

### GET /auth/me
Return the authenticated user's profile.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **Rate limit** | 300/minute (user) |
| **200** | `{user_id, username, email, status, roles[]}` |
| **403** | User is blacklisted or anonymized |

### POST /auth/unlock/{user_id}
Clear an account lockout.

| | |
|---|---|
| **Auth** | Bearer — `admin` role required |
| **200** | `{message, user_id}` |
| **404** | User not found |

---

## Risk Control (`/risk`)

### POST /risk/evaluate
Evaluate a risk event for the caller. Records a `RiskEvent` row.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **Request** | `event_type` (str, required), `ip` (str), `device_id` (str), `metadata` (object); `user_id` (int, admin-only override) |
| **200** | `{decision: allow\|challenge\|throttle\|deny, reasons[]}` |
| **403** | Caller's IP or user is blacklisted |

Non-admin callers: supplied `user_id` is ignored; caller's own ID is always used.

### GET /risk/events
Paginated audit of risk events.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Query** | `user_id`, `ip`, `event_type`, `decision`, `date_from`, `date_to`, `page`, `per_page` |
| **200** | `{items[], page, per_page, total}` |

### POST /risk/blacklist
Add an entry to the blacklist.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Request** | `target_type` (user\|device\|ip), `target_id` (str), `reason` (str), `start_at` (ISO), `end_at` (ISO, optional) |
| **201** | Blacklist entry object |

### GET /risk/blacklist
List active blacklist entries.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | Array of entry objects |

### DELETE /risk/blacklist/{id}
Soft-delete a blacklist entry (sets `end_at = now`).

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | Updated entry |
| **404** | Not found |

### POST /risk/blacklist/{id}/appeal
Submit or view an appeal for a blacklist entry.

| | |
|---|---|
| **Auth** | Bearer — OLA enforced |
| **Rules** | `user`-type entry: affected user or admin/reviewer; `device`/`ip`: admin/reviewer only |
| **200** | `{appeal_status: pending}` |
| **403** | Caller is not the affected user or a privileged role |
| **404** | Entry not found |

### PATCH /risk/blacklist/{id}/appeal
Approve or reject a pending appeal.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Request** | `appeal_status` (approved\|rejected) |
| **200** | Updated entry |
| **404** | Not found |

---

## Profiles & Visibility Groups (`/profiles`)

### GET /profiles/{user_id}
Get a user's profile (visibility-filtered).

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **200** | Profile object |
| **403** | Insufficient visibility permission |
| **404** | User not found |

### PATCH /profiles/me
Update the caller's own profile.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **Rate limit** | 30/minute (user) |
| **Request** | `display_name`, `bio`, `interest_tags_json`, `media_references_json`, `visibility_scope`, `visibility_group_id` |
| **200** | Updated profile |
| **404** | Profile not found |
| **422** | Validation error |

### POST /profiles/{user_id}/follow
Follow a user.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **201** | `{message}` |
| **409** | Already following |

### DELETE /profiles/{user_id}/follow
Unfollow a user.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **200** | `{message}` |
| **404** | Follow relationship not found |

### POST /profiles/groups
Create a visibility group.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **Request** | `name` (str, required), `member_ids[]` (int, optional) |
| **201** | `{id, name, owner_id}` |

### GET /profiles/groups/{id}
Get a visibility group (owner or member only).

| | |
|---|---|
| **Auth** | Bearer (any role) — OLA enforced |
| **200** | `{id, name, owner_id, members[]}` |
| **403** | Caller is neither owner nor member |
| **404** | Group not found |

### POST /profiles/groups/{id}/members
Add a member to a visibility group.

| | |
|---|---|
| **Auth** | Bearer — owner or `admin` |
| **Request** | `user_id` (int, required) |
| **201** | `{message}` |
| **403** | Not owner |
| **404** | Group or user not found |
| **409** | Already a member |

---

## Compliance (`/compliance`)

### POST /compliance/export-request
Request a GDPR data export for the caller's own account.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **201** | `{request_id, status: pending}` |

### POST /compliance/export-request/{id}/process
Admin: generate the export JSON file.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | `{request_id, status: complete, file}` |
| **404** | Request not found |

### GET /compliance/export-request/{id}/download
Download the generated export file.

| | |
|---|---|
| **Auth** | Bearer — owner or `admin`; IDOR-protected (non-admin sees only own exports) |
| **200** | JSON file download |
| **403** | Not owner (returns 403, never 404, to prevent enumeration) |
| **404** | Request not found or not yet processed |

### POST /compliance/deletion-request
Submit a deletion request for the caller's own account.

| | |
|---|---|
| **Auth** | Bearer (any role) |
| **201** | `{request_id, status: pending}` |

### POST /compliance/deletion-request/{id}/process
Admin: anonymize the user account (see Deletion Flow in design.md).

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | `{status: anonymized}` |
| **404** | Request not found |
| **500** | Unexpected internal error — generic message only (no internal detail exposed) |

### GET /compliance/requests
Admin: list all data requests with pagination.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Query** | `page`, `per_page`, `type` (export\|deletion), `status` (pending\|complete) |
| **200** | `{items[], page, per_page, total}` |

---

## Admin Governance (`/admin`)

### GET /admin/users
List all users (paginated, sensitive fields masked by default).

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Query** | `page`, `per_page` |
| **200** | `{items[{id, username, email, status, phone, address, dob, roles[]}], page, per_page, total}` — `phone`/`address`/`dob` masked unless purpose header present |

### GET /admin/users/{id}
Get a single user. Sensitive fields masked unless `X-Data-Access-Purpose` header provided.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Header** | `X-Data-Access-Purpose: <reason>` (optional; triggers audit log entry) |
| **200** | User object (masked or unmasked) |
| **404** | Not found |

### PATCH /admin/users/{id}
Update user role or status.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Request** | `role` (admin\|moderator\|reviewer\|user), `status` (str) |
| **200** | Updated user object |
| **404** | Not found |
| **422** | Unknown role name |

### GET /admin/audit-logs
Paginated audit log query.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Query** | `page`, `per_page`, `actor_id`, `entity_type`, `action`, `date_from`, `date_to` |
| **200** | `{items[], page, per_page, total}` |

### GET /admin/master-records/{entity_type}/{id}
Get entity current status and immutable history chain.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | `{current_status, history[{from_status, to_status, changed_at, reason, snapshot_json}]}` |
| **404** | Not found |

### POST /admin/master-records/{entity_type}/{id}/transition
Transition entity to a new status; appends a history row.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Request** | `to_status` (str), `reason` (str) |
| **200** | Updated master record |
| **404** | Not found |

---

## Policy Rules Engine (`/policies`)

### POST /policies
Create a new policy draft.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Request** | `policy_type` (str), `name` (str), `semver` (str), `effective_from` (ISO), `rules_json` (str); optional: `effective_until` (ISO), `description` |
| **201** | Policy object with `status: draft` |
| **403** | Not admin |

### PATCH /policies/{id}
Update a draft policy (rejected for non-draft statuses).

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | Updated policy |
| **404** | Not found |
| **409** | Policy is not in `draft` status |

### POST /policies/{id}/validate
Run pre-release validation checks on a draft policy.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | `{valid: bool, errors[]}` |
| **Checks** | Schema, semver > active version, effective_from < effective_until, neither date in the past |
| **404** | Not found |

### POST /policies/{id}/activate
Promote a validated policy to active; supersedes any prior active version.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | Activated policy |
| **404** | Not found |
| **409** | Policy not in `validated` status |

### GET /policies/resolve
Resolve the active policy rules for a given type and user.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Query** | `policy_type` (required), `user_id` (required) |
| **200** | `{rules_json: {…}}` |
| **400** | Missing required query params |
| **404** | No active policy for type |

### POST /policies/{id}/canary
Set a policy as canary with a rollout percentage.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **Request** | `rollout_pct` (int 0–100, required), `segment` (str, optional) |
| **200** | `{rollout_pct, status: canary}` |
| **404** | Not found |

### POST /policies/{id}/rollback
Roll back the active policy; re-activates the previous version.

| | |
|---|---|
| **Auth** | Bearer — `admin` role |
| **200** | `{status: rolled_back}` |
| **404** | Not found |
