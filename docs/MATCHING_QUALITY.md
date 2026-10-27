# CareerHunter AI — quality-first matching and Telegram policy

Updated 2026-10-27. This feature uses existing public ATS endpoints, the
current GitHub Actions runner, and the existing private Render app. No new
paid service, payment method, subscription, or external AI API is required.

## Candidate evidence

- New-grad, **Intern**, Internship, Junior and Graduate titles receive
  early-career points. Generic and senior roles must not be boosted merely
  because they mention Python or AI in a description.
- Explicit `Remote Worldwide` ATS *location* can count toward the remote
  location score even if the ATS omits a separate `remote_type` field.
  A bare "Remote" is not proof that someone in Türkiye may work there.
- Regional "US-only", "UK-only" or equivalent restrictions override
  general remote/global wording. Work permit, sponsorship, and employment
  eligibility are never inferred as legally guaranteed.
- This scoring improvement runs in the **Render-hosted collector**. The
  GitHub change alone is not proof that Render is already running the
  updated scorer: verify production deployment before claiming live impact.

## Telegram digest behavior

- The authenticated daily scan remains the source of new postings.
- The outgoing report distinguishes **scored / review candidates** from
  **priority** ones; "strong" score alone does not certify suitability.
- A priority item needs (1) score above the daily threshold,
  (2) a junior/intern level, and (3) an eligible geographic signal.
  Even then, individual legal, visa and employer conditions need checking.
- Send higher-confidence records first; report score and relevant
  uncertainties clearly. Low/moderate matches are explicitly labelled.
- `TELEGRAM_DAILY_ITEM_LIMIT` is 10 by default and is clamped to 1..20.
  It limits *messages*, not storage; unseen results remain in the private
  database. Each Telegram batch holds 5 links. No new token or server is needed.
- On `GITHUB_RUN_ATTEMPT` greater than 1, don't repeat a daily notification.
  The Github Action should report SKIP, not pretend another delivery occurred.
- Telegram's positive message ID proves Bot API acceptance and a screenshot
  verifies inbox receipt; neither proves that a message was read.

## Operator verification

1. Review GitHub Tests and Controlled E2E for the merged commit.
2. Confirm Render has deployed the newer commit before assuming new match
   scores exist in the database. Do not modify the legacy database manually.
3. The next successful Daily Career Intelligence workflow should process
   ATS listings. Confirm its processed/new counts separately.
4. Inspect CareerHunter Telegram Report: positive Bot API receipt required;
   count and link list reflect the daily cap and explain hidden extras.
5. Compare priority/review counts and rejection reasons over multiple days;
   never lower score thresholds solely to inflate notification volume.

**0 TL condition:** Keep Neon / Render / GitHub on verified free tiers,
respect quota and expiry risks, and do not claim 24/7 availability. The
separate Neon migration plan (PR #1) is not a completed production cutover.
