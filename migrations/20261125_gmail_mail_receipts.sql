-- Durable Gmail receipt schema for least-privilege worker roles.
-- Apply once as the authorized schema owner; the worker performs no DDL.
BEGIN;

CREATE TABLE IF NOT EXISTS public.careerhunter_approved_mail_receipts (
    mail_hash varchar(64) PRIMARY KEY,
    claimed_at varchar(40) NOT NULL,
    status varchar(24) NOT NULL,
    provider_receipt_hash varchar(64),
    provider_message_id varchar(120),
    company_key varchar(64)
);

ALTER TABLE public.careerhunter_approved_mail_receipts
    ADD COLUMN IF NOT EXISTS provider_receipt_hash varchar(64),
    ADD COLUMN IF NOT EXISTS provider_message_id varchar(120),
    ADD COLUMN IF NOT EXISTS company_key varchar(64);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careerhunter_mail_sender') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA public TO careerhunter_mail_sender';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE '
             || 'ON TABLE public.careerhunter_approved_mail_receipts '
             || 'TO careerhunter_mail_sender';
    ELSE
        RAISE NOTICE 'careerhunter_mail_sender is absent; rerun this migration after role provisioning';
    END IF;
END
$$;

COMMIT;
