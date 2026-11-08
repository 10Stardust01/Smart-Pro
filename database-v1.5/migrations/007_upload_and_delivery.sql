BEGIN;
CREATE TABLE upload_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id),
  user_id uuid NOT NULL REFERENCES users(id),
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','UPLOADED','COMPLETE','REJECTED')),
  storage_key text NOT NULL UNIQUE,
  document_version_id uuid REFERENCES document_versions(id),
  sha256 char(64) CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint CHECK(size_bytes>0),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CHECK((status='COMPLETE')=(document_version_id IS NOT NULL AND completed_at IS NOT NULL))
);
ALTER TABLE outbox_events ADD COLUMN claim_token uuid;
ALTER TABLE outbox_events ADD COLUMN last_error text;
ALTER TABLE outbox_events ADD CONSTRAINT claimed_lease_present CHECK(
  (status='CLAIMED')=(claim_token IS NOT NULL AND claimed_until IS NOT NULL));

CREATE FUNCTION smartpro_upload_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'upload record is historical' USING ERRCODE='23514'; END IF;
  IF (NEW.id,NEW.document_id,NEW.user_id,NEW.storage_key,NEW.created_at)
     IS DISTINCT FROM (OLD.id,OLD.document_id,OLD.user_id,OLD.storage_key,OLD.created_at)
    OR OLD.status='COMPLETE' THEN
    RAISE EXCEPTION 'upload identity/completed record immutable' USING ERRCODE='23514'; END IF;
  IF NEW.status='COMPLETE' AND NOT EXISTS(
    SELECT 1 FROM document_versions dv JOIN file_assets fa ON fa.id=dv.file_asset_id
    WHERE dv.id=NEW.document_version_id AND dv.document_id=NEW.document_id AND dv.uploaded_by=NEW.user_id
      AND fa.storage_key=NEW.storage_key AND fa.sha256=NEW.sha256 AND fa.size_bytes=NEW.size_bytes
      AND fa.upload_status='READY' AND fa.verified_at IS NOT NULL) THEN
    RAISE EXCEPTION 'upload completion must match verified immutable version' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_upload_session BEFORE UPDATE OR DELETE ON upload_sessions
  FOR EACH ROW EXECUTE FUNCTION smartpro_upload_identity();

CREATE FUNCTION smartpro_claim_outbox(batch_size integer,lease_seconds integer)
RETURNS SETOF outbox_events LANGUAGE plpgsql AS $$
BEGIN
  IF batch_size NOT BETWEEN 1 AND 100 OR lease_seconds NOT BETWEEN 1 AND 3600 THEN
    RAISE EXCEPTION 'invalid worker claim bounds' USING ERRCODE='23514'; END IF;
  RETURN QUERY WITH candidates AS (
    SELECT id FROM outbox_events WHERE (status='PENDING' AND available_at<=clock_timestamp())
      OR (status='CLAIMED' AND claimed_until<=clock_timestamp())
    ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT batch_size
  ) UPDATE outbox_events e SET status='CLAIMED',claim_token=gen_random_uuid(),
      claimed_until=clock_timestamp()+make_interval(secs=>lease_seconds),attempts=e.attempts+1
    FROM candidates c WHERE e.id=c.id RETURNING e.*;
END;
$$;
CREATE FUNCTION smartpro_ack_outbox(event_id uuid,token uuid) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  UPDATE outbox_events SET status='PROCESSED',processed_at=clock_timestamp(),claim_token=NULL,claimed_until=NULL
    WHERE id=event_id AND status='CLAIMED' AND claim_token=token AND claimed_until>clock_timestamp();
  RETURN FOUND;
END;
$$;
CREATE FUNCTION smartpro_retry_outbox(event_id uuid,token uuid,error_text text,max_attempts integer DEFAULT 5)
RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF max_attempts NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'invalid retry limit' USING ERRCODE='23514'; END IF;
  UPDATE outbox_events SET status=CASE WHEN attempts>=max_attempts THEN 'DEAD' ELSE 'PENDING' END,
    available_at=clock_timestamp()+make_interval(secs=>least(3600,power(2,least(attempts,10)))::integer),
    claim_token=NULL,claimed_until=NULL,last_error=left(error_text,2000)
    WHERE id=event_id AND status='CLAIMED' AND claim_token=token AND claimed_until>clock_timestamp();
  RETURN FOUND;
END;
$$;
-- Owner/superuser DDL remains outside the application security boundary.
-- An ordinary service role must never have TRUNCATE/DDL or grant-management rights.
COMMIT;
