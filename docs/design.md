# Design Document — MediaVault Asset Governance & Membership Backend

## 1. Module Boundaries

```
app/
├── api/          HTTP layer — blueprints, request parsing, auth decorators, HTTP responses
├── services/     Business logic — stateless functions called by API layer and other services
├── models/       SQLAlchemy ORM — data definitions, immutability listeners, relationships
├── utils/        Cross-cutting helpers — auth decorators, rate-limit key functions
└── extensions/   Flask extension singletons — db, limiter, migrate
```

**Dependency rule**: `api` → `services` → `models`. Services never import from `api`.
All inter-service calls (e.g., `compliance_service` calling `audit_service`) stay within the
`services` layer. Models contain no business logic beyond column constraints and event listeners.

---

## 2. Authentication & Authorization Model

### Authentication
- Token-based: `POST /auth/login` → opaque `Session.token` (random 32-byte URL-safe string).
- Sessions stored in the `sessions` table with `expires_at` (24 h TTL) and `revoked_at`.
- Every protected route is wrapped with `@require_auth` (from `app/utils/auth_utils.py`), which:
  1. Reads `Authorization: Bearer <token>`.
  2. Looks up the active, non-expired, non-revoked session in the DB.
  3. Sets `g.current_user` to the associated `User` object.
  4. Checks the active `Blacklist` table — IP, device, and user-level blocks return **403**.

### Authorization
Two levels applied in combination:

| Level | Mechanism | Example |
|---|---|---|
| Route-level (RBAC) | `@require_role("admin")` decorator | Only admins reach `POST /policies` |
| Object-level (OLA) | Inline check inside the handler | `entry.target_id == str(caller.id)` for blacklist appeals |

Role hierarchy (highest to lowest): `admin` > `moderator` > `reviewer` > `user`.
Roles are stored in `roles` / `user_roles` tables. Promotion only via `PATCH /admin/users/<id>`.
Only the four canonical roles are accepted; unknown role names are rejected with **422**.

### Session Token Lifecycle
```
login → create session (token, expires_at=+24h)
refresh → revoke old session, create new session
logout → set revoked_at = now
anonymize user → revoke all sessions (process_deletion step 5)
```

---

## 3. Risk Decision Flow

`POST /risk/evaluate` records a `RiskEvent` and returns a `{decision, reasons}` response.

### Severity Tiers (evaluated in priority order)

| Tier | Decision | Signal → Reason code |
|---|---|---|
| HIGH | `deny` | ≥3 registrations/IP/10 min → `rapid_account_creation` |
| HIGH | `deny` | ≥10 distinct-user login failures/IP/5 min → `credential_stuffing` |
| HIGH | `deny` | ≥5 profile edits/user/10 min → `high_velocity_profile_edit` |
| CHALLENGE | `challenge` | ≥4 net unfulfilled reserves/user/60 min → `reserve_abandon` |
| MEDIUM | `throttle` | ≥3 redeems AND ≥3 refunds/user/24 h → `coupon_cycling` |
| — | `allow` | no signals |

Decision precedence: if any HIGH signal fires → `deny`; else if any CHALLENGE → `challenge`;
else if any MEDIUM → `throttle`; else `allow`.

### Caller-Identity Enforcement
Non-admin callers have their submitted `user_id` ignored; the service always uses
`g.current_user.id`. Admins may supply an explicit `user_id` to evaluate on behalf of another
user (e.g., for fraud investigation tooling).

### Thresholds
Default thresholds are hardcoded in `risk_service.py`. An active `risk_thresholds` policy
(managed via the Policy Rules Engine) overrides them when present.

---

## 4. Compliance: Deletion, Export, and Retention

### Deletion Flow (`process_deletion` in `compliance_service.py`)

Executed in a single DB transaction; rolled back in full on any failure:

| Step | Action |
|---|---|
| 1 | Overwrite user PII: username → `deleted_<id>`, email → `deleted_<id>@redacted.local` |
| 2 | Clear profile PII: bio, display_name, interest_tags, media_references |
| 3 | Remove visibility group memberships |
| 4 | Set `user.status = 'anonymized'` |
| 5 | Revoke all active sessions |
| 6 | Reassign ledger entries to sentinel user (see Retention Policy below) |
| 7 | Leave `coupon_redemptions` untouched (legal audit trail) |
| 8 | Append `MasterRecordHistory` row with `to_status='anonymized'` |
| 9 | Write audit log (`user_anonymized`) including ledger retention counts |
| 10 | Mark `DataRequest` complete |

### Retention Policy (Step 6)

Constant: `LEDGER_RETENTION_YEARS = 7` (`compliance_service.py`).
Helper: `is_within_retention_window(created_at) → bool`.

```
Within 7-year window  → legally mandated retention (financial regulations)
Beyond 7-year window → retained anyway (audit history + FK integrity)
Policy: NEVER hard-delete ledger rows
```

All ledger entries (regardless of age) are reassigned to `deleted_user_sentinel` via raw SQL
(bypasses ORM immutability listener). The audit log records `ledger_within_retention_window`
and `ledger_beyond_retention_window` counts for regulatory traceability.

### Export Flow
`POST /compliance/export-request` → `POST /compliance/export-request/<id>/process` → JSON file
written to `app/data/exports/<request_id>.json`. Download available at
`GET /compliance/export-request/<id>/download` (owner or admin only; IDOR-protected).

---

## 5. Logging & Forensics Model

### Structured Request Log
Every HTTP request is logged as JSON to stderr via `app/__init__.py` after-request hook:
`timestamp`, `level`, `request_id` (UUID per request), `method`, `path`, `status_code`,
`duration_ms`, `user_id`, `ip`.

### Audit Log (`audit_logs` table)
Written by `audit_service.log_audit(...)` on every security-relevant action:

| Column | Purpose |
|---|---|
| `actor_id` | User who performed the action (null for system events) |
| `actor_role` | Role string at time of action |
| `action` | Event name (e.g., `login_success`, `user_anonymized`, `policy_rollback`) |
| `entity_type` | Object type affected (user, policy, asset …) |
| `entity_id` | PK of affected object |
| `detail_json` | Action-specific metadata (IP, purpose header, counts …) |
| `ip` | Request IP |
| `created_at` | Immutable timestamp |

Sensitive field access (unmasked via `X-Data-Access-Purpose` header) is logged with the
purpose value in `detail_json` under `action='admin_view_user_unmasked'`.

### Master Record & History (`master_records`, `master_record_history`)
Every tracked entity (currently: users) has a `MasterRecord` with `current_status`.
Every status transition appends an immutable `MasterRecordHistory` row with:
`from_status`, `to_status`, `changed_by`, `reason`, `changed_at`, `snapshot_json`.
Attempts to UPDATE a history row raise `RuntimeError` via SQLAlchemy event listener.

### Sensitive Field Encryption
`phone_encrypted`, `address_encrypted`, `dob_encrypted` are encrypted at rest using
AES-GCM via `encryption_service.py`. The `FIELD_ENCRYPTION_KEY` environment variable
is required at startup; missing key aborts with `RuntimeError`. Fields are masked
(`***-***-XXXX`, `[REDACTED]`) on admin GET unless `X-Data-Access-Purpose` header is present.

---

## 6. Rate Limiting

Limits are enforced by Flask-Limiter with an in-memory store (configurable via
`RATELIMIT_STORAGE_URI`). Key functions:

| Scope | Key | Limit |
|---|---|---|
| Per-IP (unauthenticated) | Remote address | 60/hour on `/auth/login`, `/auth/register` |
| Per-user (authenticated write) | `user:<id>` | 30/minute on `/auth/logout`, `/auth/refresh` |
| Per-user (authenticated read) | `user:<id>` | 300/minute on `/auth/me` |

Responses exceeding the limit return **429** with a `Retry-After` header.
