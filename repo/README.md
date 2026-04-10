# MediaVault API

A MediaVault Asset Governance and Membership system backend API.

## Quick Start

```bash
docker compose up
```

## CI Flow

```bash
git clone <repo-url>
cd repo/
docker compose build
docker compose up -d
./run-tests.sh
```

Note: `run-tests.sh` is self-sufficient — no prior `pip install` is needed.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIELD_ENCRYPTION_KEY` | **Yes** | — | Base64-encoded **32-byte** AES-256 key for field-level encryption. Must decode to exactly 32 bytes — any other length causes a hard startup failure. Generate with: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"` |
| `DATABASE_URL` | No | `sqlite:///data/mediavault.db` | SQLAlchemy database URL |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `LOG_FILE` | No | — | Path to log file for rotation |

### Generating FIELD_ENCRYPTION_KEY

```bash
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

The resulting string is a base64 representation of 32 random bytes.  The app
validates the decoded length at startup and will refuse to start with a key
that does not decode to exactly 32 bytes.

## API Examples

### Health Check

```bash
curl http://localhost:5000/healthz
```

Response:
```json
{"status": "ok", "db": "connected"}
```

### Auth

```bash
# Register
curl -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "email": "alice@example.com", "password": "Secret123!Pass"}'

# Login
curl -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "Secret123!Pass"}'

# Logout
curl -X POST http://localhost:5000/auth/logout \
  -H "Authorization: Bearer <token>"
```

### Device Identity

Auth-protected endpoints accept an optional `X-Device-Id` header.  When
present, the middleware checks the blacklist for an active entry with
`target_type = "device"` matching that value and returns `403` if found.

```bash
curl http://localhost:5000/auth/me \
  -H "Authorization: Bearer <token>" \
  -H "X-Device-Id: device-abc-123"
```

A blocked device receives:
```json
{"error": "forbidden", "message": "Device is blacklisted", "code": "device_blacklisted"}
```

### Risk

```bash
# Evaluate risk for a user action (optionally include device id)
curl -X POST http://localhost:5000/risk/evaluate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -H "X-Device-Id: device-abc-123" \
  -d '{"event_type": "login", "ip": "1.2.3.4"}'
```

### Membership

```bash
# Get current user's membership
curl http://localhost:5000/membership/me \
  -H "Authorization: Bearer <token>"

# Accrue points
curl -X POST http://localhost:5000/membership/accrue \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"user_id": 1, "amount": 100, "currency": "points", "reason": "purchase", "idempotency_key": "order-123"}'
```

### Marketing

```bash
# List campaigns
curl http://localhost:5000/marketing/campaigns \
  -H "Authorization: Bearer <admin-token>"

# Validate incentives / coupon
curl -X POST http://localhost:5000/marketing/validate-incentives \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"coupon_code": "SAVE10", "order_total_cents": 5000}'
```

### Assets

```bash
# Create an asset (admin/moderator)
curl -X POST http://localhost:5000/assets \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"title": "My Image", "asset_type": "image", "category_id": 1, "source": "internal", "copyright": "CC0"}'

# List assets
curl http://localhost:5000/assets \
  -H "Authorization: Bearer <token>"
```

### Profiles

```bash
# Get a user's profile
curl http://localhost:5000/profiles/1 \
  -H "Authorization: Bearer <token>"

# Follow a user
curl -X POST http://localhost:5000/profiles/1/follow \
  -H "Authorization: Bearer <token>"
```

### Policies

`policy_type` must be one of: `booking`, `course_selection`, `warehouse_ops`,
`pricing`, `risk`, `rate_limit`, `membership`, `coupon`.  Any other value is
rejected with HTTP 422.

```bash
# Create a policy (admin)
curl -X POST http://localhost:5000/policies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{
    "policy_type": "risk",
    "name": "Production Risk Policy",
    "semver": "1.0.0",
    "effective_from": "2026-01-01T00:00:00",
    "rules_json": "{\"rapid_account_creation_threshold\": 5}"
  }'

# Activate a policy (admin)
curl -X POST http://localhost:5000/policies/1/activate \
  -H "Authorization: Bearer <admin-token>"

# Resolve applicable policy for a user (optionally with segment for canary-aware resolution)
curl "http://localhost:5000/policies/resolve?policy_type=risk&user_id=42&segment=beta_users" \
  -H "Authorization: Bearer <admin-token>"

# Create a canary rollout scoped to a user segment
curl -X POST http://localhost:5000/policies/1/canary \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"rollout_pct": 20, "segment": "beta_users"}'
```

**Canary / Segment Resolution Precedence**

1. Segment-specific rollout (exact `segment` match) — highest priority
2. Global rollout (`segment` is `null`) — applies to all callers without a more-specific match
3. No rollout row → every user receives the full active policy

### Compliance

```bash
# Submit a data export request
curl -X POST http://localhost:5000/compliance/export-request \
  -H "Authorization: Bearer <token>"

# Submit a deletion request
curl -X POST http://localhost:5000/compliance/deletion-request \
  -H "Authorization: Bearer <token>"

# Process an export (admin)
curl -X POST http://localhost:5000/compliance/export-request/7/process \
  -H "Authorization: Bearer <admin-token>"

# Process a deletion (admin) - anonymises PII, retains ledger entries for 7 years
curl -X POST http://localhost:5000/compliance/deletion-request/8/process \
  -H "Authorization: Bearer <admin-token>"
```

### Admin

```bash
# List users (admin)
curl http://localhost:5000/admin/users \
  -H "Authorization: Bearer <admin-token>"

# List audit logs (admin)
curl http://localhost:5000/admin/audit-logs \
  -H "Authorization: Bearer <admin-token>"
```

### API Documentation

Visit `http://localhost:5000/docs` for the interactive Swagger UI.

The OpenAPI spec is available at `http://localhost:5000/openapi.json`.

## Project Structure

```
repo/
├── app/
│   ├── __init__.py          # Application factory (create_app)
│   ├── extensions.py        # SQLAlchemy, flask-smorest, limiter instances
│   ├── api/                 # Route blueprints (one file per domain)
│   │   ├── auth.py          # /auth — register, login, logout, captcha gate
│   │   ├── membership.py    # /membership — tiers, ledger, accrue, redeem
│   │   ├── assets.py        # /assets — CRUD, download grants, visibility
│   │   ├── profiles.py      # /profiles — follow, block, hide, search
│   │   ├── marketing.py     # /marketing — campaigns, coupons, incentives
│   │   ├── policies.py      # /policies — versions, rollouts, resolve
│   │   ├── risk.py          # /risk — evaluate, signal ingestion
│   │   ├── compliance.py    # /compliance — export/deletion requests
│   │   ├── admin.py         # /admin — users, audit logs, master records
│   │   ├── captcha.py       # /captcha — challenge issue and verify
│   │   └── health.py        # /healthz — liveness probe
│   ├── models/              # SQLAlchemy ORM models (32 tables)
│   │   ├── auth.py          # User, Role, Session, LoginAttempt
│   │   ├── membership.py    # MembershipTier, Membership, Ledger
│   │   ├── asset.py         # Asset, Taxonomy, Dictionary, DownloadGrant, VisibilityGroup
│   │   ├── profile.py       # Profile, ProfileFollow, ProfileBlock, ProfileHide
│   │   ├── marketing.py     # Campaign, Coupon, CouponRedemption
│   │   ├── policy.py        # Policy, PolicyVersion, PolicyRollout
│   │   ├── risk.py          # RiskEvent, Blacklist
│   │   ├── captcha.py       # CaptchaChallenge, CaptchaToken
│   │   ├── compliance.py    # DataRequest, MasterRecord, MasterRecordHistory
│   │   └── audit.py         # AuditLog
│   ├── services/            # Business logic (OLA enforced here)
│   │   ├── auth_service.py
│   │   ├── membership_service.py
│   │   ├── asset_service.py
│   │   ├── profile_service.py
│   │   ├── marketing_service.py
│   │   ├── policy_service.py
│   │   ├── risk_service.py
│   │   ├── compliance_service.py
│   │   ├── master_record_service.py
│   │   ├── captcha_service.py
│   │   ├── audit_service.py
│   │   └── encryption_service.py
│   └── utils/               # Auth helpers, CAPTCHA puzzle loader
│       ├── auth_utils.py
│       └── captcha_utils.py
├── migrations/              # Alembic migration scripts
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
├── tests/                   # pytest suite (193 tests, ≥80% coverage)
│   ├── conftest.py
│   ├── test_foundation.py
│   ├── test_auth.py
│   ├── test_membership.py
│   ├── test_assets.py
│   ├── test_profiles.py
│   ├── test_marketing.py / test_coupons.py
│   ├── test_policies.py
│   ├── test_risk.py
│   ├── test_captcha.py
│   ├── test_compliance.py
│   ├── test_admin.py
│   ├── test_logging.py
│   ├── test_performance.py
│   └── test_security_idor.py
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── run-tests.sh             # Self-sufficient test runner (creates own venv)
├── wsgi.py
└── .env.example             # Template — copy to .env and fill in secrets
```

## Known Limitations

- Single-machine SQLite deployment; not horizontally scalable.
- No JWT; sessions stored in DB — horizontal scaling requires a shared session store.
- All operations are offline; no third-party integrations (email, SMS, payment processors).
- WAL mode is SQLite-only; switching to PostgreSQL requires removing the WAL pragma setup.
- Rate limiting uses in-memory storage by default; counters reset on restart and are not shared across processes.
- File uploads are not supported; assets store metadata only, not binary content.
- No background job processing; compliance deletion and data export requests must be processed manually or by a separate worker.
