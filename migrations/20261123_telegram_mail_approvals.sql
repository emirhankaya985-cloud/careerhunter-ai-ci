-- Apply as the Neon database owner to careerhunter_live.
-- Idempotent: safe to re-run; grants only table access to the application writer.
CREATE TABLE IF NOT EXISTS public.careerhunter_telegram_mail_approvals (
    request_id varchar(32) PRIMARY KEY,
    created_at varchar(40) NOT NULL,
    expires_at varchar(40) NOT NULL,
    status varchar(24) NOT NULL,
    payload text NOT NULL,
    recipient_hash varchar(64) NOT NULL
);
GRANT USAGE ON SCHEMA public TO careerhunter_mail_sender;
GRANT SELECT, INSERT, UPDATE ON TABLE public.careerhunter_telegram_mail_approvals TO careerhunter_mail_sender;
