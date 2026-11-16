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
