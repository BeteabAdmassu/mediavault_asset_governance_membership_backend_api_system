# Test Coverage Audit

## Project Type Detection
- Declared in README top: `Project Type: backend` (`repo/README.md:3`).
- Light inspection confirms backend-only shape: Flask API modules in `repo/app/api/*.py`, Python test suite in `repo/tests/*.py`, no frontend source/test stack.

## Backend Endpoint Inventory
- Inventory method: static extraction of `url_prefix` + `@blp.route(...)` + `def get/post/patch/delete` in:
  - `repo/app/api/admin.py`
  - `repo/app/api/assets.py`
  - `repo/app/api/auth.py`
  - `repo/app/api/captcha.py`
  - `repo/app/api/compliance.py`
  - `repo/app/api/health.py`
  - `repo/app/api/marketing.py`
  - `repo/app/api/membership.py`
  - `repo/app/api/policies.py`
  - `repo/app/api/profiles.py`
  - `repo/app/api/risk.py`
- Total resolved endpoints: **86** unique `METHOD + PATH`.

## API Test Mapping Table
| Endpoint | Covered | Test type | Test file | Evidence |
|---|---|---|---|---|
| `GET /admin/users` | yes | true no-mock HTTP | `repo/tests/test_admin.py` | `test_audit_log_on_admin_action` (`repo/tests/test_admin.py:132`) |
| `GET /admin/users/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_admin.py` | `test_sensitive_fields_masked_by_default` (`repo/tests/test_admin.py:242`) |
| `PATCH /admin/users/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_admin.py` | `test_admin_patch_unknown_role_rejected` (`repo/tests/test_admin.py:449`) |
| `GET /admin/audit-logs` | yes | true no-mock HTTP | `repo/tests/test_admin.py` | `test_audit_log_pagination` (`repo/tests/test_admin.py:408`) |
| `GET /admin/audit-logs/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_admin_coverage.py` | `test_audit_log_detail_found` (`repo/tests/test_admin_coverage.py:179`) |
| `GET /admin/master-records/<entity_type>/<int:entity_id>` | yes | true no-mock HTTP | `repo/tests/test_admin.py` | `test_get_master_record_history_chain` (`repo/tests/test_admin.py:370`) |
| `POST /admin/master-records/<entity_type>/<int:entity_id>/transition` | yes | true no-mock HTTP | `repo/tests/test_admin.py` | `test_master_record_history_appended_on_transition` (`repo/tests/test_admin.py:46`) |
| `POST /taxonomy/categories` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `_setup_basics` (`repo/tests/test_assets.py:21`) |
| `GET /taxonomy/categories` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_get_category_tree` (`repo/tests/test_assets.py:102`) |
| `PATCH /taxonomy/categories/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_category_update_persists` (`repo/tests/test_assets_coverage.py:60`) |
| `DELETE /taxonomy/categories/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_category_delete_returns_message` (`repo/tests/test_assets_coverage.py:77`) |
| `POST /taxonomy/tags` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_create_tag_returns_id_and_name` (`repo/tests/test_assets_coverage.py:96`) |
| `GET /taxonomy/tags` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_list_tags_returns_array` (`repo/tests/test_assets_coverage.py:104`) |
| `POST /taxonomy/dictionaries` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `_setup_basics` (`repo/tests/test_assets.py:26`) |
| `GET /taxonomy/dictionaries` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_dictionary_list_by_dimension_returns_matching` (`repo/tests/test_assets_coverage.py:118`) |
| `DELETE /taxonomy/dictionaries/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_dictionary_delete_returns_message` (`repo/tests/test_assets_coverage.py:130`) |
| `POST /assets` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_create_asset_image_success` (`repo/tests/test_assets.py:141`) |
| `GET /assets` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_asset_list_filter_by_type` (`repo/tests/test_assets.py:420`) |
| `GET /assets/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_soft_delete_asset` (`repo/tests/test_assets.py:382`) |
| `PATCH /assets/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_update_asset_revalidates` (`repo/tests/test_assets.py:346`) |
| `DELETE /assets/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_soft_delete_asset` (`repo/tests/test_assets.py:378`) |
| `POST /assets/<int:id>/grant-download` | yes | true no-mock HTTP | `repo/tests/test_assets.py` | `test_grant_download_rate_limited` (`repo/tests/test_assets.py:548`) |
| `DELETE /assets/<int:id>/grant-download/<int:user_id>` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_revoke_download_grant` (`repo/tests/test_profiles.py:454`) |
| `GET /assets/<int:id>/download` | yes | true no-mock HTTP | `repo/tests/test_assets_coverage.py` | `test_restricted_asset_denied_without_grant` (`repo/tests/test_assets_coverage.py:228`) |
| `POST /auth/register` | yes | true no-mock HTTP | `repo/tests/conftest.py` | `_register_and_login` (`repo/tests/conftest.py:62`) |
| `POST /auth/login` | yes | true no-mock HTTP | `repo/tests/conftest.py` | `_register_and_login` (`repo/tests/conftest.py:66`) |
| `POST /auth/logout` | yes | true no-mock HTTP | `repo/tests/test_auth.py` | `test_logout_success` (`repo/tests/test_auth.py:190`) |
| `POST /auth/refresh` | yes | true no-mock HTTP | `repo/tests/test_auth.py` | `test_refresh_token` (`repo/tests/test_auth.py:207`) |
| `GET /auth/me` | yes | true no-mock HTTP | `repo/tests/test_admin_coverage.py` | `test_audit_log_filter_by_actor_id` (`repo/tests/test_admin_coverage.py:122`) |
| `POST /auth/unlock/<int:user_id>` | yes | true no-mock HTTP | `repo/tests/test_auth.py` | `test_admin_unlock` (`repo/tests/test_auth.py:281`) |
| `GET /captcha/challenge` | yes | true no-mock HTTP | `repo/tests/test_auth_coverage.py` | `test_login_with_solved_captcha_succeeds` (`repo/tests/test_auth_coverage.py:78`) |
| `POST /captcha/verify` | yes | true no-mock HTTP | `repo/tests/test_auth_coverage.py` | `test_login_with_solved_captcha_succeeds` (`repo/tests/test_auth_coverage.py:85`) |
| `POST /compliance/export-request` | yes | true no-mock HTTP | `repo/tests/test_compliance.py` | `_create_export_request` (`repo/tests/test_compliance.py:17`) |
| `POST /compliance/export-request/<int:id>/process` | yes | true no-mock HTTP | `repo/tests/test_compliance.py` | `_process_export` (`repo/tests/test_compliance.py:23`) |
| `GET /compliance/export-request/<int:id>/download` | yes | true no-mock HTTP | `repo/tests/test_compliance.py` | `test_export_download_before_process` (`repo/tests/test_compliance.py:61`) |
| `POST /compliance/deletion-request` | yes | true no-mock HTTP | `repo/tests/test_compliance.py` | `_create_deletion_request` (`repo/tests/test_compliance.py:31`) |
| `POST /compliance/deletion-request/<int:id>/process` | yes | true no-mock HTTP | `repo/tests/test_compliance.py` | `_process_deletion` (`repo/tests/test_compliance.py:37`) |
| `GET /compliance/requests` | yes | true no-mock HTTP | `repo/tests/test_compliance.py` | `test_compliance_requests_list_shape` (`repo/tests/test_compliance.py:736`) |
| `GET /healthz` | yes | true no-mock HTTP | `repo/tests/test_foundation.py` | `test_healthz_ok` (`repo/tests/test_foundation.py:21`) |
| `POST /marketing/campaigns` | yes | true no-mock HTTP | `repo/tests/test_coupons.py` | `_create_campaign` (`repo/tests/test_coupons.py:40`) |
| `GET /marketing/campaigns` | yes | true no-mock HTTP | `repo/tests/test_marketing_coverage.py` | `test_campaign_list_pagination_shape` (`repo/tests/test_marketing_coverage.py:63`) |
| `GET /marketing/campaigns/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_coupons.py` | `test_redemption_count_incremented` (`repo/tests/test_coupons.py:350`) |
| `PATCH /marketing/campaigns/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_marketing_coverage.py` | `test_campaign_update` (`repo/tests/test_marketing_coverage.py:93`) |
| `DELETE /marketing/campaigns/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_marketing_coverage.py` | `test_campaign_delete_and_verify_gone` (`repo/tests/test_marketing_coverage.py:122`) |
| `POST /marketing/coupons` | yes | true no-mock HTTP | `repo/tests/test_coupons.py` | `_create_coupon` (`repo/tests/test_coupons.py:52`) |
| `GET /marketing/coupons` | yes | true no-mock HTTP | `repo/tests/test_marketing_coverage.py` | `test_coupon_list_pagination_shape` (`repo/tests/test_marketing_coverage.py:157`) |
| `GET /marketing/coupons/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_marketing_coverage.py` | `test_coupon_detail` (`repo/tests/test_marketing_coverage.py:169`) |
| `POST /marketing/validate-incentives` | yes | true no-mock HTTP | `repo/tests/test_coupons.py` | `_validate` (`repo/tests/test_coupons.py:75`) |
| `POST /marketing/redeem` | yes | true no-mock HTTP | `repo/tests/test_coupons.py` | `_redeem` (`repo/tests/test_coupons.py:88`) |
| `GET /marketing/redemptions` | yes | true no-mock HTTP | `repo/tests/test_marketing_coverage.py` | `test_redemptions_list_pagination_shape` (`repo/tests/test_marketing_coverage.py:215`) |
| `GET /membership/tiers` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_default_tiers_seeded` (`repo/tests/test_membership.py:35`) |
| `POST /membership/tiers` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_create_tier` (`repo/tests/test_membership.py:49`) |
| `PATCH /membership/tiers/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_membership_coverage.py` | `test_update_tier_persists` (`repo/tests/test_membership_coverage.py:45`) |
| `GET /membership/me` | yes | true no-mock HTTP | `repo/tests/test_coupons.py` | `_get_user_id` (`repo/tests/test_coupons.py:62`) |
| `POST /membership/ledger/credit` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_credit_ledger` (`repo/tests/test_membership.py:173`) |
| `POST /membership/ledger/debit` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_debit_ledger_success` (`repo/tests/test_membership.py:205`) |
| `GET /membership/ledger` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_credit_ledger` (`repo/tests/test_membership.py:195`) |
| `GET /membership/ledger/me` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_ledger_pagination` (`repo/tests/test_membership.py:333`) |
| `POST /membership/accrue` | yes | true no-mock HTTP | `repo/tests/test_membership.py` | `test_accrue_points_floor_rounding` (`repo/tests/test_membership.py:68`) |
| `GET /policies` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_policies_list_pagination_shape` (`repo/tests/test_policies.py:1021`) |
| `POST /policies` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_create_draft_policy` (`repo/tests/test_policies.py:85`) |
| `GET /policies/resolve` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_resolve_returns_active_rules` (`repo/tests/test_policies.py:217`) |
| `GET /policies/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_activate_sets_previous_superseded` (`repo/tests/test_policies.py:192`) |
| `PATCH /policies/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_patch_draft_allowed` (`repo/tests/test_policies.py:94`) |
| `POST /policies/<int:id>/validate` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `_validate_policy` (`repo/tests/test_policies.py:50`) |
| `POST /policies/<int:id>/activate` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `_activate_policy` (`repo/tests/test_policies.py:57`) |
| `POST /policies/<int:id>/canary` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_canary_rollout` (`repo/tests/test_policies.py:235`) |
| `POST /policies/<int:id>/rollback` | yes | true no-mock HTTP | `repo/tests/test_policies.py` | `test_rollback_restores_previous` (`repo/tests/test_policies.py:280`) |
| `GET /profiles/<int:user_id>` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_public_scope_visible_to_any_user` (`repo/tests/test_profiles.py:137`) |
| `PATCH /profiles/me` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_update_own_profile` (`repo/tests/test_profiles.py:96`) |
| `GET /profiles/me/followers` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_follow_unfollow` (`repo/tests/test_profiles.py:392`) |
| `GET /profiles/me/following` | yes | true no-mock HTTP | `repo/tests/test_profiles_coverage.py` | `test_follow_appears_in_following` (`repo/tests/test_profiles_coverage.py:102`) |
| `POST /profiles/<int:user_id>/follow` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_mutual_followers_scope_stub_for_non_mutual` (`repo/tests/test_profiles.py:163`) |
| `DELETE /profiles/<int:user_id>/follow` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_follow_unfollow` (`repo/tests/test_profiles.py:402`) |
| `POST /profiles/<int:user_id>/block` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_block_hides_profile` (`repo/tests/test_profiles.py:294`) |
| `DELETE /profiles/<int:user_id>/block` | yes | true no-mock HTTP | `repo/tests/test_profiles_coverage.py` | `test_unblock_user` (`repo/tests/test_profiles_coverage.py:146`) |
| `POST /profiles/<int:user_id>/hide` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_hide_user` (`repo/tests/test_profiles.py:368`) |
| `POST /profiles/groups` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_custom_group_scope_visible_to_member` (`repo/tests/test_profiles.py:221`) |
| `GET /profiles/groups/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_visibility_group_membership` (`repo/tests/test_profiles.py:518`) |
| `POST /profiles/groups/<int:id>/members` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_visibility_group_membership` (`repo/tests/test_profiles.py:530`) |
| `DELETE /profiles/groups/<int:id>/members/<int:user_id>` | yes | true no-mock HTTP | `repo/tests/test_profiles.py` | `test_visibility_group_membership` (`repo/tests/test_profiles.py:538`) |
| `POST /risk/evaluate` | yes | true no-mock HTTP | `repo/tests/test_device_blacklist.py` | `test_blocked_device_denied_on_risk_evaluate` (`repo/tests/test_device_blacklist.py:56`) |
| `GET /risk/events` | yes | true no-mock HTTP | `repo/tests/test_performance.py` | `test_risk_events_list_p95_under_250ms` (`repo/tests/test_performance.py:20`) |
| `POST /risk/blacklist` | yes | true no-mock HTTP | `repo/tests/test_risk.py` | `test_blacklist_create` (`repo/tests/test_risk.py:188`) |
| `GET /risk/blacklist` | yes | true no-mock HTTP | `repo/tests/test_risk.py` | `test_blacklist_create` (`repo/tests/test_risk.py:203`) |
| `DELETE /risk/blacklist/<int:id>` | yes | true no-mock HTTP | `repo/tests/test_risk.py` | `test_blacklist_soft_delete` (`repo/tests/test_risk.py:209`) |
| `POST /risk/blacklist/<int:id>/appeal` | yes | true no-mock HTTP | `repo/tests/test_risk.py` | `test_appeal_flow` (`repo/tests/test_risk.py:320`) |
| `PATCH /risk/blacklist/<int:id>/appeal` | yes | true no-mock HTTP | `repo/tests/test_risk.py` | `test_appeal_flow` (`repo/tests/test_risk.py:349`) |

## API Test Classification
1. **True No-Mock HTTP**
   - Dominant suite pattern: `client.get/post/patch/delete` across route handlers with real app+DB fixtures (e.g., `repo/tests/conftest.py`, domain suites in `repo/tests/test_*.py`).
2. **HTTP with Mocking**
   - `repo/tests/test_foundation.py:test_healthz_db_unreachable` patches `app.extensions.db.session.execute`.
   - `repo/tests/test_auth.py:test_login_lockout_resets_after_window` patches `app.services.auth_service.datetime`.
   - `repo/tests/test_captcha.py:test_challenge_expires` patches `app.services.captcha_service._now`.
   - `repo/tests/test_compliance.py:test_deletion_is_transactional` and `repo/tests/test_compliance.py:test_deletion_error_response_does_not_leak_internals` patch `app.services.compliance_service.transition_master_record`.
3. **Non-HTTP (unit/integration without HTTP)**
   - `repo/tests/test_service_edge_cases.py` (service/model invariant checks).

## Mock Detection (Strict)
- `from unittest.mock import patch` detected in:
  - `repo/tests/test_foundation.py:3`
  - `repo/tests/test_auth.py:8`
  - `repo/tests/test_captcha.py:5`
  - `repo/tests/test_compliance.py:6`
  - `repo/tests/test_logging.py:5` (import present; no active patch block in inspected file)
- Active patch blocks detected in:
  - `repo/tests/test_foundation.py:30`
  - `repo/tests/test_auth.py:172`
  - `repo/tests/test_captcha.py:102`
  - `repo/tests/test_compliance.py:360`
  - `repo/tests/test_compliance.py:499`

## Coverage Summary
- Total endpoints: **86**
- Endpoints with HTTP tests: **86**
- Endpoints with true no-mock HTTP evidence: **86**
- HTTP coverage: **100.00%**
- True API coverage: **100.00%**

## Unit Test Summary

### Backend Unit Tests
- Primary backend unit/service files:
  - `repo/tests/test_service_edge_cases.py`
  - `repo/tests/test_encryption_key.py`
  - `repo/tests/test_device_blacklist.py`
- Modules covered (static evidence):
  - controllers/routes: broad direct HTTP route validation across all API domains (`repo/tests/test_*_coverage.py`, `repo/tests/test_*`).
  - services: auth, captcha, compliance, membership/policy/risk edge conditions (`repo/tests/test_service_edge_cases.py`, `repo/tests/test_compliance.py`, `repo/tests/test_auth.py`).
  - repositories/models: policy DB constraint and ledger immutability checks (`repo/tests/test_policies.py`, `repo/tests/test_membership.py`).
  - auth/guards/middleware: role checks, IDOR/forbidden paths (`repo/tests/test_security_idor.py`, `repo/tests/test_admin.py`, `repo/tests/test_profiles.py`).
- Important backend modules not strongly unit-isolated (mostly API-level tested):
  - `repo/app/services/asset_service.py`
  - `repo/app/services/profile_service.py`
  - `repo/app/services/marketing_service.py`
  - `repo/app/services/master_record_service.py`

### Frontend Unit Tests
- Frontend test files: **NONE**
- Frontend frameworks/tools detected: **NONE**
- Components/modules covered: **NONE**
- Important frontend modules not tested: **N/A (no frontend module tree detected)**
- **Frontend unit tests: MISSING** (not a critical gap for backend project type)

Cross-layer observation:
- No frontend layer is present; FE↔BE balance check is not applicable.

## API Observability Check
- Strong: tests generally include explicit method/path, request body/query, and response assertions.
- Weak spots still present (quality, not breadth):
  - some rate-limit tests assert only terminal status (`429`) without validating error payload contract (e.g., `repo/tests/test_membership.py:test_accrue_rate_limited`, `repo/tests/test_compliance.py:test_export_process_rate_limited`).
  - some list/filter tests are envelope-heavy vs deep business semantics.

## Tests Check
- Coverage breadth is now complete at endpoint level (86/86) with mostly real HTTP path execution.
- Suite depth is high overall (success/failure/auth/validation/IDOR/rate-limit/retention flows).
- `run_tests.sh` is Docker-first and executes tests in Docker (`repo/run_tests.sh:23-37`) — **OK**.
- Strict caveat: Docker path still tries host `python3/python` first for key generation before container fallback (`repo/run_tests.sh:28-30`); host fallback path also installs deps locally (`repo/run_tests.sh:42-86`).

## Test Coverage Score (0-100)
**93/100**

## Score Rationale
- Full endpoint coverage with meaningful HTTP-path tests and broad domain/risk/authz coverage raises confidence.
- Score reduced for residual quality issues (some shallow assertions) and mixed reproducibility posture in `run_tests.sh` (host-coupled key generation attempt + host fallback flow).

## Key Gaps
- Strengthen selected assertions from status-only to payload/semantic validations in rate-limit and list-filter paths.
- Consider making Docker path fully container-pure by removing host-Python key-generation attempt in `run_tests.sh`.
- Expand isolated service-unit coverage for asset/profile/marketing service internals.

## Confidence & Assumptions
- Confidence: **high** for endpoint inventory and coverage mapping; **medium-high** for sufficiency scoring.
- Static inspection only; no execution performed.

---

# README Audit

README target: `repo/README.md` (exists).

## High Priority Issues
- None blocking under current strict gates.

## Medium Priority Issues
- Step 3 login token extraction uses host `python -c` in shell pipeline (`repo/README.md:73-76`), introducing optional host tooling dependency in docs flow.
- README asserts seed script presence/usage; this is valid now, but operationally depends on script packaging in deployments (`repo/scripts/seed_roles.py`).

## Low Priority Issues
- Demo bootstrap workflow is long and operationally dense; can be simplified with a dedicated make target or script wrapper.

## Hard Gate Failures
- **Formatting/readability:** PASS
- **Startup instruction includes `docker-compose up`:** PASS (`repo/README.md:10`)
- **Access method (URL+port):** PASS (`repo/README.md:13`)
- **Verification method (curl/API examples):** PASS (`repo/README.md:132-315`)
- **Environment rules (no install/manual DB setup guidance):** PASS
  - No `npm install`, `pip install`, `apt-get`, or manual DB statement blocks in README.
  - Role bootstrap uses Docker-contained script (`repo/README.md:60`, `repo/scripts/seed_roles.py`).
- **Demo credentials for auth with all roles:** PASS (`repo/README.md:84-89`)

## README Verdict
**PASS**

Reason: all strict hard gates are satisfied; remaining issues are quality/ergonomics rather than compliance failures.

---

## Final Combined Verdicts
- **Test Coverage Audit Verdict:** Strong, endpoint-complete, confidence-building with minor quality caveats.
- **README Audit Verdict:** **PASS** under strict compliance gates.
