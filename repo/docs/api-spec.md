# MediaVault API Specification

> Interactive Swagger UI: `GET /docs`  
> Machine-readable OpenAPI 3.0.3 spec: `GET /openapi.json`

All endpoints that require authentication accept a Bearer token in the
`Authorization` header:

```
Authorization: Bearer <token>
```

---

## Device Identity

Auth-protected endpoints optionally read the `X-Device-Id` request header to
identify the calling device.  When the header is present, the middleware checks
the `blacklists` table for an active entry with `target_type = "device"` and
`target_id = <header value>`.

**Header**

| Header | Required | Description |
|--------|----------|-------------|
| `X-Device-Id` | No | Opaque device identifier (string, max 255 chars). Required for device-level blacklist enforcement to be applied. Requests without the header bypass device blacklist checks. |

**Blacklist semantics** — an entry is *active* when:
- `start_at <= NOW`
- `end_at IS NULL OR end_at > NOW`

**Blocked response** (HTTP 403):

```json
{
  "error": "forbidden",
  "message": "Device is blacklisted",
  "code": "device_blacklisted"
}
```

Endpoints enforced: all routes protected by `@require_auth` (includes `/auth/me`,
`/risk/evaluate`, all `/policies/*` write endpoints, and others).

---

## Auth

### `POST /auth/register`

Register a new user account.

**Request**
```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "Secret123!Pass"
}
```

**Response 201**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "status": "active"
}
```

**Constraints**
- `username`: 3–64 characters, unique
- `email`: valid email format, unique
- `password`: 3–64 characters

---

### `POST /auth/login`

Authenticate and receive a session token.

**Request**
```json
{
  "username": "alice",
  "password": "Secret123!Pass"
}
```

**Response 200**
```json
{
  "token": "<session-token>",
  "expires_at": "2026-04-11T12:00:00+00:00"
}
```

**Lockout**: 5 consecutive failures within 15 minutes locks the account for 30 minutes.

---

### `GET /auth/me`

Return the authenticated user's own profile.

**Headers**: `Authorization: Bearer <token>`, optional `X-Device-Id`

**Response 200**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "status": "active",
  "roles": ["user"]
}
```

---

### `POST /auth/logout`

Revoke the current session token.

**Headers**: `Authorization: Bearer <token>`

**Response 200**
```json
{"message": "Logged out"}
```

---

## Risk

### `POST /risk/evaluate`

Evaluate a risk signal for an event.

**Headers**: `Authorization: Bearer <token>`, optional `X-Device-Id`

**Request**
```json
{
  "event_type": "login",
  "ip": "1.2.3.4",
  "device_id": "device-abc-123",
  "user_id": 42
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `event_type` | Yes | e.g. `login`, `registration`, `reserve`, `coupon_apply`, `profile_edit` |
| `ip` | No | Client IP address |
| `device_id` | No | Device identifier (also checked via `X-Device-Id` header in auth middleware) |
| `user_id` | No | Target user ID |

**Response 200**
```json
{
  "decision": "deny",
  "reasons": ["rapid_account_creation"],
  "event_id": 99
}
```

`decision` values: `allow`, `challenge`, `throttle`, `deny`

---

### Blacklist CRUD

#### `POST /risk/blacklist`

Create a blacklist entry. Admin only.

**Request**
```json
{
  "target_type": "device",
  "target_id": "device-abc-123",
  "reason": "Suspicious activity",
  "start_at": "2026-04-10T00:00:00Z",
  "end_at": null
}
```

`target_type` values: `user`, `device`, `ip`

---

## Policies

### Allowed Policy Types

`policy_type` must be one of the following enumerated values.  Unknown values
are rejected with **422 Unprocessable Entity**.

| Type | Description |
|------|-------------|
| `booking` | Booking concurrency and session rules |
| `course_selection` | Course selection limits |
| `warehouse_ops` | Warehouse operation thresholds |
| `pricing` | Pricing configuration |
| `risk` | Risk signal thresholds |
| `rate_limit` | API rate-limit configuration |
| `membership` | Membership tier configuration |
| `coupon` | Coupon discount limits |

---

### `POST /policies`

Create a policy in `draft` status. Admin only.

**Request**
```json
{
  "policy_type": "risk",
  "name": "Production Risk Policy",
  "semver": "1.0.0",
  "effective_from": "2026-01-01T00:00:00",
  "rules_json": "{\"rapid_account_creation_threshold\": 5}",
  "effective_until": null,
  "description": "Initial risk thresholds"
}
```

**Response 201** — returns the policy object with `"status": "draft"`.

**422** is returned when `policy_type` is not in the allowlist.

---

### `GET /policies/resolve`

Resolve the effective policy rules for a given user. Admin only.

**Query parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `policy_type` | Yes | One of the allowed policy types |
| `user_id` | Yes | Integer user ID for canary bucketing |
| `segment` | No | Caller segment string (e.g. `beta_users`) for segment-aware rollout resolution |

**Canary rollout semantics**

When a `PolicyRollout` row exists for the active policy, deterministic
hash-bucketing (`MD5(user_id) % 100 < rollout_pct`) is used to decide whether
this user is in the canary cohort.

**Segment precedence (highest to lowest)**:

1. Segment-specific rollout: `PolicyRollout.segment == requested segment` (exact match)
2. Global rollout: `PolicyRollout.segment IS NULL`
3. No rollout → the entire active policy applies to every user

A user whose segment does not match any segment-specific rollout and there is no
global rollout receives the full active (non-canary) policy.

**Example — user in beta_users segment, canary at 100%**

```
GET /policies/resolve?policy_type=pricing&user_id=42&segment=beta_users
Authorization: Bearer <admin-token>
```

**Response 200**
```json
{
  "rules_json": {
    "base_price_cents": 2000
  }
}
```

---

### `POST /policies/{id}/canary`

Create a canary rollout for a policy. Admin only.

**Request**
```json
{
  "rollout_pct": 20,
  "segment": "beta_users"
}
```

`segment` is optional. Omit (or send `null`) for a global rollout that applies
to users regardless of segment.

---

## Profiles

### `GET /profiles/{id}`

Return a user's profile, filtered by visibility scope. Authenticated users only.

**Response 200** — full profile (when requester has access)
```json
{
  "user_id": 1,
  "display_name": "Alice",
  "bio": "...",
  "interest_tags": null,
  "media_references": null,
  "visibility_scope": "public",
  "visibility_group_id": null
}
```

**Stub profile** (when requester does not meet visibility requirements)
```json
{
  "user_id": 1,
  "display_name": "Alice"
}
```

`visibility_scope` values: `public`, `mutual_followers`, `custom_group`

- `public` — full profile returned to any authenticated user
- `mutual_followers` — full profile only when A follows B and B follows A; otherwise stub
- `custom_group` — full profile only when requester is a member of the profile's visibility group; otherwise stub

**403** is returned when either party has blocked the other.

---

### Visibility Groups

#### `POST /profiles/groups`

Create a visibility group. Authenticated users only. The creator becomes the owner.

**Request**
```json
{"name": "Close Friends", "member_ids": [2, 3]}
```

**Response 201**
```json
{"id": 5, "name": "Close Friends", "owner_id": 1}
```

---

#### `GET /profiles/groups/{id}`

Return group info with member list.

**Access**: owner or any current member. Admins without membership are denied.  
Other users receive **403**.

**Response 200**
```json
{"id": 5, "name": "Close Friends", "owner_id": 1, "members": [2, 3]}
```

---

#### `POST /profiles/groups/{id}/members`

Add a member to a visibility group.

**Access**: **group owner only**. Non-owners (including admins without ownership) receive **403**.

**Request**
```json
{"user_id": 4}
```

**Response 201**
```json
{"message": "member added"}
```

| Status | Condition |
|--------|-----------|
| 201 | Member added successfully |
| 403 | Caller is not the group owner |
| 404 | Group not found |
| 409 | User is already a member |

---

#### `DELETE /profiles/groups/{id}/members/{user_id}`

Remove a member from a visibility group.

**Access**: **group owner only**. Non-owners (including admins without ownership) receive **403**.

**Response 200**
```json
{"message": "member removed"}
```

| Status | Condition |
|--------|-----------|
| 200 | Member removed successfully |
| 403 | Caller is not the group owner |
| 404 | Group or member not found |

---

## Compliance

### `POST /compliance/export-request`

Submit a GDPR data export request for the authenticated user.

**Headers**: `Authorization: Bearer <token>`

**Request body**: none required

**Response 201**
```json
{
  "request_id": 7,
  "status": "pending"
}
```

To download the generated file after processing, use
`GET /compliance/export-request/{id}/download`.

---

### `POST /compliance/export-request/{id}/process`

Process a pending export request and write the export JSON file to disk. Admin only.

**Response 200**
```json
{
  "request_id": 7,
  "status": "complete"
}
```

The export file is written server-side; use the `/download` endpoint to retrieve it.  
Note: `export_path` is **not** included in this response.

---

### `GET /compliance/export-request/{id}/download`

Download the generated export file. Owner or admin only.

**Response**: `application/json` file attachment (`export_{id}.json`).

| Status | Condition |
|--------|-----------|
| 200 | File returned as attachment |
| 403 | Requester is neither the request owner nor an admin |
| 404 | Export not found or not yet complete |

---

### `POST /compliance/deletion-request`

Submit a GDPR deletion request for the authenticated user.

**Request body**: none required

**Response 201**
```json
{
  "request_id": 8,
  "status": "pending"
}
```

---

### `POST /compliance/deletion-request/{id}/process`

Process a deletion request: anonymise PII, revoke sessions. Admin only.  
Ledger entries are reassigned to the sentinel user (7-year retention) and
are never hard-deleted.

**Response 200**
```json
{
  "request_id": 8,
  "status": "complete"
}
```

---

## Error Response Shape

All error responses use a consistent JSON envelope:

```json
{
  "error": "<machine_readable_code>",
  "message": "<human_readable_description>",
  "code": "<optional_sub_code>"
}
```

| HTTP Status | `error` value |
|-------------|---------------|
| 400 | `bad_request` |
| 401 | `unauthorized` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 409 | `conflict` |
| 422 | `unprocessable_entity` |
| 429 | `too_many_requests` |
| 500 | `internal_server_error` |

Device blacklist 403 additionally includes `"code": "device_blacklisted"`.
