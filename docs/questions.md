# Business Logic Questions Log

---

1. **Authentication — Lockout Window**
   - **Question**: Does the 15-minute lockout window reset on a fixed schedule (e.g. every 15 min from first attempt) or is it a rolling window relative to each attempt?
   - **My Understanding**: A rolling window is safer — it prevents an attacker from timing attempts to reset the counter on a fixed boundary.
   - **Solution**: Implemented as a rolling window. On each login attempt, count rows in `login_attempts` where `attempted_at >= now - 15 min`. If count ≥ 5, lock the account for 30 minutes from the current timestamp.

---

2. **Membership — Points Accrual Rounding**
   - **Question**: "1 point per $1.00 eligible spend, rounded down" — does rounding apply to the total order amount or per line item?
   - **My Understanding**: The prompt references a single `eligible_amount` per accrual call, implying it is the caller's responsibility to pass the eligible total. Rounding happens once on that total.
   - **Solution**: `points = floor(eligible_amount_cents / 100)`. A single `POST /membership/accrue` call is made per order with the pre-calculated eligible total. Per-line-item logic lives outside this service.

---

3. **Coupons — Stacking "at most 2 incentives"**
   - **Question**: Does the 2-incentive stacking limit apply only to explicitly submitted coupon codes, or does it also count automatic membership discounts applied by the system?
   - **My Understanding**: The prompt scopes stacking to the coupon/campaign system. Membership-tier benefits are a separate pricing concern not governed by this rule.
   - **Solution**: The stacking limit is enforced only against the `coupon_codes[]` array submitted to `POST /marketing/validate-incentives`. If more than 2 codes are submitted, the entire request is rejected with 422.

---

4. **Coupons — "Same benefit type" conflict rule**
   - **Question**: Does `percent_off` conflict with `fixed_off` since both reduce the order price, or does conflict mean only an exact match on the `benefit_type` enum value?
   - **My Understanding**: The prompt says "same benefit type" — treating `percent_off` and `fixed_off` as the same type would make most coupon combinations impossible, which contradicts a 2-stack allowance. The intent is exact enum match.
   - **Solution**: Conflict is triggered only when two coupons share the identical `benefit_type` value (e.g. both `percent_off`). `percent_off` + `fixed_off` is allowed.

---

5. **Ledger — Immutability and Corrections**
   - **Question**: The ledger is append-only and no UPDATE is allowed. How are refunds or erroneous credits handled?
   - **My Understanding**: Double-entry bookkeeping pattern — corrections are new entries, not modifications to existing ones.
   - **Solution**: Refunds and corrections are recorded as new debit entries with `reason = "refund"` or `reason = "correction"` and a `reference_id` pointing to the original entry. The balance is always the running SUM of all entries.

---

6. **Compliance — 7-Year Ledger Retention Clock**
   - **Question**: When a deletion request is processed, does the 7-year financial retention period start from the deletion date or from each individual transaction date?
   - **My Understanding**: Financial regulations typically require retention from the transaction date, not the deletion date. Starting the clock at deletion could allow records to be purged prematurely if a user deletes immediately after a transaction.
   - **Solution**: The 7-year clock runs from each ledger entry's `created_at`. Deletion anonymizes PII only — ledger rows are never deleted. The sentinel deleted-user FK preserves referential integrity indefinitely.

---

7. **Policy Engine — Canary Segment Membership**
   - **Question**: "Canary rollout percentages by user segment" — how is it determined whether a specific user falls in the canary group without storing per-user state?
   - **My Understanding**: Deterministic hashing avoids any stored state and gives consistent results across requests for the same user.
   - **Solution**: `hash(str(user_id)) % 100 < rollout_pct`. A user always falls in the same bucket, so their experience is consistent across requests. The `segment` field (`new_users` / `all`) further filters eligibility before the hash check.

---

8. **Profiles — Custom Group Visibility with No Group Assigned**
   - **Question**: If a user sets `visibility_scope = custom_group` but has not been added to any visibility group, who can see their full profile?
   - **My Understanding**: The intent of `custom_group` is to restrict visibility. With no group members, the logical result is that nobody (except the user themselves and Admins) can see the full profile.
   - **Solution**: If `visibility_scope = custom_group` and the viewer is not a member of any of the profile owner's groups, the viewer receives the stub response `{user_id, display_name}` only. The owner and Admins always see the full profile.

---

9. **CAPTCHA — Required on First Login Attempt or Only After Failure?**
   - **Question**: The prompt says CAPTCHA is combined with auth. Is a CAPTCHA token required on the very first login attempt or only after the first failed attempt?
   - **My Understanding**: Requiring CAPTCHA on every login adds friction for legitimate users. The prompt lists CAPTCHA as a control against abuse, suggesting it triggers after suspicious activity.
   - **Solution**: `POST /auth/register` always requires a CAPTCHA token. `POST /auth/login` requires a CAPTCHA token only after the first failed attempt (i.e. from attempt 2 onward). This is enforced by checking `login_attempts` count before requiring the `X-Captcha-Token` header.

---

10. **Risk Engine — Signal Threshold Levels (HIGH vs MEDIUM)**
    - **Question**: The prompt defines 5 anomaly signals but does not specify which signals map to HIGH (deny) vs MEDIUM (throttle).
    - **My Understanding**: Signals that directly indicate credential attacks (`credential_stuffing`, `rapid_account_creation`, `high_velocity_profile_edit`) are more dangerous than behavioral signals (`reserve_abandon`, `coupon_cycling`).
    - **Solution**: Default mapping stored in the `risk` policy type; hardcoded as fallback:
      - HIGH → deny: `credential_stuffing`, `rapid_account_creation`, `high_velocity_profile_edit`
      - MEDIUM → throttle: `reserve_abandon`, `coupon_cycling`
      Operators can override via the policy engine without a code change.

---

11. **Master Records — Initial Status on Entity Creation**
    - **Question**: When a master record is auto-created for a new entity (user, asset, policy, campaign, blacklist), what is the initial `current_status` value?
    - **My Understanding**: Each entity type has a natural starting state that should be reflected in the master record.
    - **Solution**: Initial status per entity type:
      - `user` → `active`
      - `asset` → `draft`
      - `policy` → `draft`
      - `campaign` → `inactive`
      - `blacklist` → `active`

---

12. **Sensitive Fields — Encryption Scope**
    - **Question**: The prompt lists `phone`, `address`, and `DOB` as sensitive fields requiring encryption at rest. Should these fields be encrypted when stored in `audit_logs` snapshots and export files too?
    - **My Understanding**: Audit logs and export files are also at-rest storage. Consistent encryption policy reduces risk surface.
    - **Solution**: Sensitive fields are always stored encrypted in the DB (including `master_record_history.snapshot_json` and the `data_requests` export file). They are decrypted only at the application layer immediately before serializing a response, never at the DB layer.
