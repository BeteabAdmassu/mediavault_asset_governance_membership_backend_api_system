# MediaVault API

Project Type: backend

A MediaVault Asset Governance and Membership system backend API.

## Quick Start

```bash
docker-compose up
```

The app starts at `http://localhost:5000`. A development-only
`FIELD_ENCRYPTION_KEY` is baked into `docker-compose.yml` so no
additional setup is required for local development.

To generate a production-grade key inside the running container:

```bash
docker-compose exec api python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

Set the result as `FIELD_ENCRYPTION_KEY` in your environment or `.env` file
before running `docker-compose up` in production.

## Demo Credentials

The system does **not** ship a pre-seeded user database.  All accounts are
created through the public registration API.  Role promotion requires a
one-time bootstrap seed (see step 2) because the `PATCH /admin/users/<id>`
endpoint itself requires admin auth.

**Step 1 — Register accounts** (API calls against the running container):

```bash
curl -s -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@demo.local","password":"DemoAdmin123!Pass"}'

curl -s -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"moderator","email":"mod@demo.local","password":"DemoMod123!Pass"}'

curl -s -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"reviewer","email":"rev@demo.local","password":"DemoRev123!Pass"}'

curl -s -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"user","email":"user@demo.local","password":"DemoUser123!Pass"}'
```

**Step 2 — Seed roles (dev-only, one-time)**:

The first admin cannot be promoted via the API (chicken-and-egg: the
role-assignment endpoint requires admin auth).  Run the bundled seed
script inside the container to bootstrap the initial role assignments:

```bash
docker-compose exec api python -m scripts.seed_roles
```

The script (`scripts/seed_roles.py`) is idempotent and safe to re-run.
Once the first admin exists, all subsequent role changes can use the API
(see step 3).

**Step 3 — Ongoing role management (API-based)**:

Once an admin account exists, promote any user through the API:

```bash
# Login as admin
TOKEN=$(curl -s -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"DemoAdmin123!Pass"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Promote user 2 to moderator
curl -X PATCH http://localhost:5000/admin/users/2 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"role": "moderator"}'
```

| Role | Username | Email | Password |
|------|----------|-------|----------|
| admin | `admin` | `admin@demo.local` | `DemoAdmin123!Pass` |
| moderator | `moderator` | `mod@demo.local` | `DemoMod123!Pass` |
| reviewer | `reviewer` | `rev@demo.local` | `DemoRev123!Pass` |
| user | `user` | `user@demo.local` | `DemoUser123!Pass` |

## Running Tests

Tests run inside Docker by default (primary path). Host fallback is
secondary and only activates when Docker is unavailable.

```bash
./run_tests.sh          # Docker-first; builds test image, runs pytest inside container
./run_tests.sh fast     # Skip slow/performance tests
```

## CI Flow

```bash
git clone <repo-url>
cd repo/
docker-compose build
docker-compose up -d
./run_tests.sh
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIELD_ENCRYPTION_KEY` | No (dev default in `docker-compose.yml`; **must** be overridden for production) | see `docker-compose.yml` | Base64-encoded **32-byte** AES-256 key for field-level encryption. Must decode to exactly 32 bytes — any other length causes a hard startup failure. Generate inside Docker: `docker-compose exec api python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"` |
| `DATABASE_URL` | No | `sqlite:///data/mediavault.db` | SQLAlchemy database URL |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `LOG_FILE` | No | — | Path to log file for rotation |

## API Documentation

Interactive Swagger UI (self-hosted, no CDN):
```
http://localhost:5000/docs
```

Machine-readable OpenAPI 3.0.3 spec:
```
http://localhost:5000/openapi.json
```

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

# Accrue points (admin only)
curl -X POST http://localhost:5000/membership/accrue \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"user_id": 1, "order_id": "order-123", "eligible_amount_cents": 10000}'
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
  -d '{"user_id": 1, "order_id": "ord-001", "order_cents": 5000, "coupon_codes": ["SAVE10"]}'
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
│   ├── services/            # Business logic (OLA enforced here)
│   └── utils/               # Auth helpers, CAPTCHA puzzle loader
├── tests/                   # pytest suite (≥80% coverage gate)
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.test
├── requirements.txt
├── run_tests.sh             # Docker-first test runner (host fallback secondary)
├── wsgi.py
└── .env.example             # Template — copy to .env and fill in secrets
```

## Known Limitations

- Single-machine SQLite deployment; not horizontally scalable.
- No JWT; sessions stored in DB — horizontal scaling requires a shared session store.
- All operations are offline; no third-party integrations (email, SMS, payment processors).
- WAL mode is SQLite-only; switching to PostgreSQL requires removing the WAL pragma setup.
- Rate limiting uses in-memory storage; the Dockerfile enforces a single Gunicorn worker (`--workers 1`) so all requests share one process and one counter. Counters reset on restart. To run multiple workers, configure a shared limiter backend (e.g., `RATELIMIT_STORAGE_URI=redis://...`).
- File uploads are not supported; assets store metadata only, not binary content.
- No background job processing; compliance deletion and data export requests must be processed manually or by a separate worker.
