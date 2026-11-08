-- Protect managed evidence from legacy direct runtime writes; owner commands only.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_document_command(uuid,uuid,text,jsonb,text)') IS NULL THEN
 RAISE EXCEPTION 'Install document workflow commands before guards'; END IF; END $$;
CREATE FUNCTION public.smartpro_is_managed_document_record(t text,r jsonb) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT FROM public.submission_requirement_bindings b
  WHERE CASE t
   WHEN 'submission_cases' THEN b.case_id=(r->>'id')::uuid
   WHEN 'submission_attempts' THEN b.case_id=(r->>'case_id')::uuid
   WHEN 'submission_items' THEN b.document_id=(r->>'document_id')::uuid
   WHEN 'approval_decisions' THEN b.case_id IN(SELECT case_id FROM public.submission_attempts WHERE id=(r->>'attempt_id')::uuid)
   WHEN 'documents' THEN b.document_id=(r->>'id')::uuid
   WHEN 'document_versions' THEN b.document_id=(r->>'document_id')::uuid
   WHEN 'upload_sessions' THEN b.document_id=(r->>'document_id')::uuid
   WHEN 'file_assets' THEN EXISTS(SELECT FROM public.upload_sessions WHERE document_id=b.document_id AND storage_key=r->>'storage_key')
   ELSE false END)
$$;
CREATE FUNCTION public.smartpro_managed_document_write_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF current_user<>pg_get_userbyid((SELECT proowner FROM pg_proc WHERE oid='public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure))
  AND (public.smartpro_is_managed_document_record(TG_TABLE_NAME,coalesce(to_jsonb(NEW),to_jsonb(OLD)))
    OR (TG_OP='UPDATE' AND public.smartpro_is_managed_document_record(TG_TABLE_NAME,to_jsonb(OLD)))) THEN
  RAISE EXCEPTION 'managed documents require authorized commands' USING ERRCODE='42501'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['submission_cases','submission_attempts','submission_items','approval_decisions','documents','document_versions','upload_sessions','file_assets'] LOOP
  EXECUTE format('CREATE TRIGGER aaa_managed_document_boundary BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.smartpro_managed_document_write_guard()',t);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_is_managed_document_record(text,jsonb),public.smartpro_managed_document_write_guard() FROM PUBLIC;
-- Boolean identity predicate only; no metadata or contents. Used by invoker guards.
GRANT EXECUTE ON FUNCTION public.smartpro_is_managed_document_record(text,jsonb) TO smartpro_runtime;
COMMIT;
