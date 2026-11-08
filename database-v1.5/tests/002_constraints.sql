-- Execute AFTER migrations and 001_seed.sql. Each negative test must reject invalid data.
\set ON_ERROR_STOP on
BEGIN;
DO $tests$
DECLARE rejected boolean;
BEGIN
  -- 1. Cross-project documents cannot be attached to an existing submission.
  INSERT INTO projects(id,department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
  VALUES('15000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000001',
         '11000000-0000-4000-8000-000000000001','13000000-0000-4000-8000-000000000001',
         'MAJOR','12000000-0000-4000-8000-000000000001','DEMO-P02','Another Project');
  INSERT INTO file_assets(id,storage_key,sha256,size_bytes,mime_type,upload_status,uploaded_by,verified_at)
  VALUES('17000000-0000-4000-8000-000000000002','demo/project2/file',repeat('b',64),1,'application/pdf','READY','00000000-0000-4000-8000-000000000001',now());
  INSERT INTO documents(id,project_id,document_type,label)
  VALUES('16000000-0000-4000-8000-000000000002','15000000-0000-4000-8000-000000000002','SYNOPSIS','Other synopsis');
  INSERT INTO document_versions(id,project_id,document_id,version_no,file_asset_id,uploaded_by)
  VALUES('18000000-0000-4000-8000-000000000002','15000000-0000-4000-8000-000000000002',
         '16000000-0000-4000-8000-000000000002',1,'17000000-0000-4000-8000-000000000002',
         '00000000-0000-4000-8000-000000000001');
  rejected:=false;
  BEGIN
    INSERT INTO submission_items(attempt_id,project_id,document_id,document_version_id)
    VALUES('1a000000-0000-4000-8000-000000000001','15000000-0000-4000-8000-000000000001',
           '16000000-0000-4000-8000-000000000002','18000000-0000-4000-8000-000000000002');
  EXCEPTION WHEN foreign_key_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: cross-project file permitted'; END IF;
  RAISE NOTICE 'PASS cross-project submission blocked';

  -- 2. Combined-mode student criterion cannot be submitted as a team score.
  rejected:=false;
  BEGIN
    INSERT INTO team_criterion_scores(assessment_id,scheme_mode_id,mode_criterion_id,marks)
    VALUES('29000000-0000-4000-8000-000000000001','24000000-0000-4000-8000-000000000003',
           '25000000-0000-4000-8000-000000000006',12);
  EXCEPTION WHEN foreign_key_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: wrong scoring scope permitted'; END IF;
  RAISE NOTICE 'PASS wrong criterion scope blocked';

  -- A separate OPEN review is required for draft scoring; the published review
  -- must not accept new assessments. This changes setup, not negative assertions.
  INSERT INTO users(id,display_name,email) VALUES('00000000-0000-4000-8000-000000000005','Test Faculty 2','faculty2@example.invalid');
  INSERT INTO department_role_assignments(user_id,department_id,role_code)
  VALUES('00000000-0000-4000-8000-000000000005','10000000-0000-4000-8000-000000000001','FACULTY');
  INSERT INTO project_reviews(id,project_id,cycle_id,policy_version_id,review_definition_id,round_no,scheme_version_id,scheme_mode_id)
  SELECT '26000000-0000-4000-8000-000000000003',project_id,cycle_id,policy_version_id,review_definition_id,3,scheme_version_id,scheme_mode_id
  FROM project_reviews WHERE id='26000000-0000-4000-8000-000000000001';
  INSERT INTO review_roster_members(id,review_id,project_id,team_id,membership_id,student_user_id)
  SELECT gen_random_uuid(),'26000000-0000-4000-8000-000000000003',project_id,team_id,membership_id,student_user_id
  FROM review_roster_members WHERE review_id='26000000-0000-4000-8000-000000000001';
  UPDATE project_reviews SET roster_locked_at=now(),review_state='OPEN' WHERE id='26000000-0000-4000-8000-000000000003';
  -- 3. Score ceiling protected on a DRAFT assessment (not merely the finalized-score lock).
  INSERT INTO evaluator_assignments(id,review_id,faculty_user_id)
  VALUES('28000000-0000-4000-8000-000000000002','26000000-0000-4000-8000-000000000003',
         '00000000-0000-4000-8000-000000000005');
  INSERT INTO assessments(id,review_id,scheme_mode_id,evaluator_assignment_id)
  VALUES('29000000-0000-4000-8000-000000000002','26000000-0000-4000-8000-000000000003',
         '24000000-0000-4000-8000-000000000003','28000000-0000-4000-8000-000000000002');
  rejected:=false;
  BEGIN
    INSERT INTO team_criterion_scores(assessment_id,scheme_mode_id,mode_criterion_id,marks)
    VALUES('29000000-0000-4000-8000-000000000002','24000000-0000-4000-8000-000000000003',
           '25000000-0000-4000-8000-000000000005',61);
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: over-maximum marks permitted in draft'; END IF;
  RAISE NOTICE 'PASS over-maximum marks blocked in draft';

  -- 3b. Incomplete draft assessments cannot be finalized.
  rejected:=false;
  BEGIN
    UPDATE assessments SET state='FINALIZED'
    WHERE id='29000000-0000-4000-8000-000000000002';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: incomplete assessment finalized'; END IF;
  RAISE NOTICE 'PASS incomplete assessment finalization blocked';

  -- 4. Finalized assessment scores cannot be changed.
  rejected:=false;
  BEGIN
    UPDATE team_criterion_scores SET marks=51
    WHERE assessment_id='29000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: finalized marks changed'; END IF;
  RAISE NOTICE 'PASS finalized assessment protected';

  -- 5. Activated rubrics cannot be changed directly.
  rejected:=false;
  BEGIN
    UPDATE rubric_criteria SET maximum=65
    WHERE id='23000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: locked rubric changed'; END IF;
  RAISE NOTICE 'PASS approved rubric locked';

  -- 5b. Once assessment begins, switching modes must not orphan scores.
  rejected:=false;
  BEGIN
    UPDATE project_reviews SET scheme_mode_id='24000000-0000-4000-8000-000000000001'
    WHERE id='26000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: review mode changed after assessment'; END IF;
  RAISE NOTICE 'PASS review mode fixed after assessment';

  -- 6. Locked roster cannot be edited.
  rejected:=false;
  BEGIN
    DELETE FROM review_roster_members WHERE id='27000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: locked review roster altered'; END IF;
  RAISE NOTICE 'PASS review roster locked';

  -- 7. A release is immutable (corrections create a new release).
  rejected:=false;
  BEGIN
    UPDATE result_student_scores SET total_marks=100
    WHERE release_id='2a000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: released result changed'; END IF;
  RAISE NOTICE 'PASS published result immutable';

  -- 8. Historical document versions cannot be overwritten.
  rejected:=false;
  BEGIN
    UPDATE document_versions SET version_no=9
    WHERE id='18000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: document version overwritten'; END IF;
  RAISE NOTICE 'PASS document version immutable';

  -- 8b. Referenced file identity (object key/checksum) cannot be rewritten.
  rejected:=false;
  BEGIN
    UPDATE file_assets SET storage_key='demo/changed-file-object'
    WHERE id='17000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: referenced stored object identity changed'; END IF;
  RAISE NOTICE 'PASS referenced object identity immutable';

  -- 9. Replayed idempotency keys cannot create a second record.
  INSERT INTO idempotency_records(actor_id,operation,key,request_sha256,state)
  VALUES('00000000-0000-4000-8000-000000000001','submit_synopsis','idempo-1',repeat('a',64),'IN_PROGRESS');
  rejected:=false;
  BEGIN
    INSERT INTO idempotency_records(actor_id,operation,key,request_sha256,state)
    VALUES('00000000-0000-4000-8000-000000000001','submit_synopsis','idempo-1',repeat('a',64),'IN_PROGRESS');
  EXCEPTION WHEN unique_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: duplicate idempotency key permitted'; END IF;
  RAISE NOTICE 'PASS duplicate idempotency key blocked';

  -- 10. Version-conditional update must reject stale clients.
  UPDATE submission_cases SET row_version=row_version+1
   WHERE id='19000000-0000-4000-8000-000000000001' AND row_version=999;
  IF FOUND THEN RAISE EXCEPTION 'FAIL: stale version wrote data'; END IF;
  RAISE NOTICE 'PASS stale version refused';

  -- 11. Roster membership must belong to the exact review (not another round).
  INSERT INTO project_reviews(id,project_id,cycle_id,policy_version_id,review_definition_id,
                              round_no,scheme_version_id,scheme_mode_id,review_state)
  VALUES ('26000000-0000-4000-8000-000000000002','15000000-0000-4000-8000-000000000001',
          '11000000-0000-4000-8000-000000000001','12000000-0000-4000-8000-000000000001',
          '20000000-0000-4000-8000-000000000001',2,'22000000-0000-4000-8000-000000000001',
          '24000000-0000-4000-8000-000000000003','SCHEDULED');
  INSERT INTO review_roster_members(id,review_id,project_id,team_id,membership_id,student_user_id)
  VALUES('27000000-0000-4000-8000-000000000003','26000000-0000-4000-8000-000000000002',
         '15000000-0000-4000-8000-000000000001','13000000-0000-4000-8000-000000000001',
         '14000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001');
  rejected:=false;
  BEGIN
    INSERT INTO student_criterion_scores(assessment_id,review_id,scheme_mode_id,roster_member_id,mode_criterion_id,marks)
    VALUES ('29000000-0000-4000-8000-000000000001','26000000-0000-4000-8000-000000000001',
            '24000000-0000-4000-8000-000000000003','27000000-0000-4000-8000-000000000003',
            '25000000-0000-4000-8000-000000000006',20);
  EXCEPTION WHEN foreign_key_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: different review roster accepted'; END IF;
  RAISE NOTICE 'PASS wrong review roster blocked';

  -- 12. Newly approved schemes cannot omit required rubric mappings.
  INSERT INTO scheme_versions(id,scheme_id,cycle_id,review_definition_id,version_no)
  VALUES('22000000-0000-4000-8000-000000000002','21000000-0000-4000-8000-000000000001',
         '11000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001',2);
  rejected:=false;
  BEGIN
    UPDATE scheme_versions SET state='APPROVED',approved_by='00000000-0000-4000-8000-000000000004',approved_at=now()
    WHERE id='22000000-0000-4000-8000-000000000002';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: empty scheme approved'; END IF;
  RAISE NOTICE 'PASS incomplete scheme approval blocked';

  -- 13. A pending/unverified file cannot be formally submitted.
  INSERT INTO file_assets(id,storage_key,sha256,size_bytes,mime_type,upload_status,uploaded_by,verified_at)
  VALUES('17000000-0000-4000-8000-000000000003','demo/project1/unverified',repeat('c',64),1,
         'application/pdf','PENDING','00000000-0000-4000-8000-000000000001',NULL);
  INSERT INTO documents(id,project_id,document_type,label)
  VALUES('16000000-0000-4000-8000-000000000003','15000000-0000-4000-8000-000000000001',
         'OTHER','Draft attachment');
  INSERT INTO document_versions(id,project_id,document_id,version_no,file_asset_id,uploaded_by)
  VALUES('18000000-0000-4000-8000-000000000003','15000000-0000-4000-8000-000000000001',
         '16000000-0000-4000-8000-000000000003',1,'17000000-0000-4000-8000-000000000003',
         '00000000-0000-4000-8000-000000000001');
  rejected:=false;
  BEGIN
    INSERT INTO submission_items(attempt_id,project_id,document_id,document_version_id)
    VALUES('1a000000-0000-4000-8000-000000000001','15000000-0000-4000-8000-000000000001',
           '16000000-0000-4000-8000-000000000003','18000000-0000-4000-8000-000000000003');
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: unverified file submitted'; END IF;
  RAISE NOTICE 'PASS pending file rejected';

  -- 14. Historical approved academic policy cannot be overwritten.
  rejected:=false;
  BEGIN
    UPDATE project_policy_versions SET policy_data='{"changed":true}'::jsonb
    WHERE id='12000000-0000-4000-8000-000000000001';
  EXCEPTION WHEN check_violation THEN rejected:=true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'FAIL: approved academic policy changed'; END IF;
  RAISE NOTICE 'PASS approved policy locked';

  -- 15. Correct demo results 52+34 and 52+30, and one source assessment.
  IF (SELECT total_marks FROM result_student_scores
      WHERE roster_member_id='27000000-0000-4000-8000-000000000001') <> 86 OR
     (SELECT total_marks FROM result_student_scores
      WHERE roster_member_id='27000000-0000-4000-8000-000000000002') <> 82 THEN
    RAISE EXCEPTION 'FAIL: unexpected demo grade totals';
  END IF;
  IF (SELECT count(*) FROM result_source_assessments
      WHERE release_id='2a000000-0000-4000-8000-000000000001') <> 1 THEN
    RAISE EXCEPTION 'FAIL: source assessment missing';
  END IF;
  RAISE NOTICE 'PASS synthetic published-score baseline';
END
$tests$;
ROLLBACK; -- Test-only writes never persist.
