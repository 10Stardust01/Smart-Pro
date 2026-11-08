-- Read-only reports after prepare and explicit team/profile mapping.
-- Each result must be empty before activation; output UUIDs rather than USNs.
SELECT id AS unmapped_team FROM teams WHERE curriculum_offering_id IS NULL;
SELECT DISTINCT m.user_id AS missing_student_profile
  FROM team_memberships m LEFT JOIN student_profiles s ON s.user_id=m.user_id
  WHERE s.user_id IS NULL;
SELECT a.id AS membership_a,b.id AS membership_b,a.user_id,ta.curriculum_offering_id
  FROM team_memberships a JOIN teams ta ON ta.id=a.team_id
  JOIN team_memberships b ON b.user_id=a.user_id AND a.id<b.id
  JOIN teams tb ON tb.id=b.team_id AND tb.curriculum_offering_id=ta.curriculum_offering_id
  WHERE tstzrange(a.joined_at,a.left_at,'[)') && tstzrange(b.joined_at,b.left_at,'[)');

-- Ended history may differ from the current profile. Unended/scheduled scope may not.
SELECT m.id AS incompatible_current_membership,m.user_id,t.curriculum_offering_id
  FROM team_memberships m JOIN teams t ON t.id=m.team_id
  JOIN curriculum_offerings o ON o.id=t.curriculum_offering_id
  JOIN student_profiles s ON s.user_id=m.user_id
  WHERE (m.left_at IS NULL OR m.left_at>statement_timestamp())
    AND (s.department_id,s.semester_key) IS DISTINCT FROM (o.department_id,o.semester_key);
