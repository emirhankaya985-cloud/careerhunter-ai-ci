# CareerHunter Gmail outbound — staged integration

This phase adds a tested, **disabled-by-default** route for automatic email applications. A scheduled scan may send only when the job's official ATS listing explicitly says to email a CV/application, the listing is active and freshly verified, the candidate match is at least 60, Türkiye eligibility is verified, the encrypted CV for the message language exists, and all one-time owner switches are enabled. The system never submits ATS web forms or guesses an email address. Merging code does not enable sending.

## Permissions

- Existing `GMAIL_READONLY_*` credentials remain for inbox monitoring.
- Sending requires a separate OAuth consent containing `https://www.googleapis.com/auth/gmail.send`.
- Store `GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`, `GMAIL_SEND_REFRESH_TOKEN` in private runtime configuration; never in GitHub or test logs.
- Set `CAREERHUNTER_GMAIL_SEND_ENABLED=true` **only after** credentials and vetted recipient source have been verified.
- Use an explicitly approved, least-privileged PostgreSQL database connection for the one-shot receipt ledger. Never use the read-only dashboard database role.

## Sending contract

`careerhunter.gmail_send.send_approved_once` takes an `ApprovedMail` with an explicit recipient, subject, body, verified published contact source URL, owner approval ID and true owner approval flag, plus a separately authorized ledger DSN. Automatic outreach is controlled by `CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED=true` and `CAREERHUNTER_GMAIL_AUTO_TEMPLATE_APPROVED=v1`; both must be set by the owner after reviewing the exact message template and uploading the chosen CV. The existing send switch and `gmail.send` OAuth scope are also required. Each message is claimed durably before Gmail is called. The limit is five per UTC day and one per company per day. Unconfirmed provider results remain marked for manual review and **must not be blindly retried**. The Gmail message ID is stored in the private receipt ledger; no Gmail response body or address is logged.

## Remaining production acceptance gates

1. Owner completes a new OAuth consent for `gmail.send`. The earlier `gmail.readonly` grant does not cover sending.
2. Owner selects and uploads the final English and/or Turkish CV to the encrypted owner vault, and reviews the exact v1 template before setting the approval switch.
3. At least one qualifying ATS listing must explicitly publish an application email. ATS-only roles remain visible as links and are not submitted.
4. Run the scheduled scan and confirm its accepted-send count and private Gmail receipt ledger. A provider-accepted message is not proof of delivery, reading, or employer response.

No email is sent unless all owner-controlled switches are enabled and a matching encrypted CV and eligible public application email are present.

## Owner-only send endpoint

The existing authenticated dashboard now exposes `GET /internal/owner/mail/status`, `GET /internal/owner/mail/csrf`, and `POST /internal/owner/mail/send`. The latter requires a logged-in owner, same-origin request, dedicated CSRF, explicit approval, an existing active ATS job and a **previously approved high-confidence contact** belonging to the same employer. Email address and evidence are loaded from private CRM; callers cannot inject an arbitrary destination. Durable idempotency is stable per job/contact, even if message text changes. This is not a public open relay or a new dashboard.

The owner can inspect `GET /internal/owner/application-queue` for high-scoring, source-verified active jobs. This read-only queue never submits an application. The mail status response counts eligible approved contacts and remains blocked when that count is zero, even if OAuth and database settings are present.

When the authenticated sender account differs from the address printed on the candidate's CV, set `CAREERHUNTER_APPLICATION_REPLY_TO` to the candidate's verified contact address. The Gmail account remains the actual sender; the Reply-To header directs replies to the CV address. The application form must use the same verified contact address. Do not set a forged From header.

Sending remains closed until Google grants a fresh `gmail.send` refresh token, a separate write-capable ledger database URL `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` is configured, the final CV is uploaded, and the owner approves the exact template once. The preexisting `GMAIL_READONLY_CLIENT_ID` and `GMAIL_READONLY_CLIENT_SECRET` may be reused as OAuth **client credentials**; only `GMAIL_SEND_REFRESH_TOKEN` must be new. Reusing `GMAIL_READONLY_REFRESH_TOKEN` is not permitted. The scheduled worker checks all switches and gates for every run; it does not ask for per-email confirmation. Keep automatic dispatch disabled until the owner has reviewed the template and selected/uploaded the CV.

## Encrypted owner CV vault

The private dashboard exposes an owner-authenticated browser uploader at
/internal/owner/cv/manage, GET /internal/owner/cv/status,
GET /internal/owner/cv/csrf, PUT /internal/owner/cv/tr and PUT
/internal/owner/cv/en (raw application/pdf body), owner-only PDF download routes,
and CSRF-protected DELETE routes. Files are limited to 10 MiB and are
encrypted with AES-256-GCM before insertion. Production reuses the existing private CRM PostgreSQL writer URL and requires a
base64url-encoded, random 32-byte key in CAREERHUNTER_CV_VAULT_KEY; keep the
key in Render secrets.
Losing/changing the key makes stored PDFs unrecoverable. Rotate only with an
explicit decrypt/re-encrypt migration and verified backup. The repository does
not upload local CV files. Once the owner has approved the exact template and
enabled automatic dispatch, qualifying explicitly email-based applications
may be sent automatically under the limits above.

