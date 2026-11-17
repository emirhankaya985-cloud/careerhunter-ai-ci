# CareerHunter Gmail outbound — staged integration

This phase adds a tested, **disabled-by-default** sending primitive for verified, owner-approved application emails. It is not a blanket ATS apply bot and it is **not enabled** in production merely by merging the code.

## Permissions

- Existing `GMAIL_READONLY_*` credentials remain for inbox monitoring.
- Sending requires a separate OAuth consent containing `https://www.googleapis.com/auth/gmail.send`.
- Store `GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`, `GMAIL_SEND_REFRESH_TOKEN` in private runtime configuration; never in GitHub or test logs.
- Set `CAREERHUNTER_GMAIL_SEND_ENABLED=true` **only after** credentials and vetted recipient source have been verified.
- Use an explicitly approved, least-privileged PostgreSQL database connection for the one-shot receipt ledger. Never use the read-only dashboard database role.

## Sending contract

`careerhunter.gmail_send.send_approved_once` takes an `ApprovedMail` with an explicit recipient, subject, body, verified published contact source URL, owner approval ID and true owner approval flag, plus a separately authorized ledger DSN. It refuses missing approval, unverified source URL, disabled feature and missing scope credentials. Each approved message is claimed durably before Gmail is called. There is a quota of five per UTC day. Unconfirmed provider results remain marked for manual review and **must not be blindly retried**. No Gmail response body or address is logged.

## Remaining production acceptance gates

1. Owner completes a new OAuth consent for gmail.send. The earlier gmail.readonly grant does not cover sending.
2. Import a genuine private CV/profile and independently verified employer application contacts. The public profile is an example; a job URL is not an email address.
3. Build and verify the private owner approval / outbox intake and protected scheduling integration. The current module is intentionally not called by a scheduler.
4. Run a single owner-approved real test send, verify Gmail's accepted message ID and the recipient's receipt; then enable bounded dispatch.
5. Confirm Telegram reports and safe failure behavior before claiming fully autonomous operation.

No email is sent by this change.

## Owner-only send endpoint

The existing authenticated dashboard now exposes `GET /internal/owner/mail/status`, `GET /internal/owner/mail/csrf`, and `POST /internal/owner/mail/send`. The latter requires a logged-in owner, same-origin request, dedicated CSRF, explicit approval, an existing active ATS job and a **previously approved high-confidence contact** belonging to the same employer. Email address and evidence are loaded from private CRM; callers cannot inject an arbitrary destination. Durable idempotency is stable per job/contact, even if message text changes. This is not a public open relay or a new dashboard.

The owner can inspect `GET /internal/owner/application-queue` for high-scoring, source-verified active jobs. This read-only queue never submits an application. The mail status response counts eligible approved contacts and remains blocked when that count is zero, even if OAuth and database settings are present.

When the authenticated sender account differs from the address printed on the candidate's CV, set `CAREERHUNTER_APPLICATION_REPLY_TO` to the candidate's verified contact address. The Gmail account remains the actual sender; the Reply-To header directs replies to the CV address. The application form must use the same verified contact address. Do not set a forged From header.

The form/API send is currently closed until Google grants a fresh `gmail.send` refresh token and a separate write-capable ledger database URL `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` is configured. The preexisting `GMAIL_READONLY_CLIENT_ID` and `GMAIL_READONLY_CLIENT_SECRET` may be reused as OAuth **client credentials**; only `GMAIL_SEND_REFRESH_TOKEN` must be new. Reusing `GMAIL_READONLY_REFRESH_TOKEN` is not permitted. Set `CAREERHUNTER_GMAIL_SEND_ENABLED=true` only after configuration and an owner-approved sample; unattended dispatch is not yet enabled. A Telegram audit/receipt check remains a production acceptance requirement.

## Encrypted owner CV vault

The private dashboard exposes owner-authenticated GET /internal/owner/cv/status,
GET /internal/owner/cv/csrf, PUT /internal/owner/cv/tr and PUT
/internal/owner/cv/en (raw application/pdf body), owner-only PDF download routes,
and CSRF-protected DELETE routes. Files are limited to 10 MiB and are
encrypted with AES-256-GCM before insertion. Production reuses the existing private CRM PostgreSQL writer URL and requires a
base64url-encoded, random 32-byte key in CAREERHUNTER_CV_VAULT_KEY; keep the
key in Render secrets.
Losing/changing the key makes stored PDFs unrecoverable. Rotate only with an
explicit decrypt/re-encrypt migration and verified backup. The repository does
not upload local CV files or contact employers automatically.
