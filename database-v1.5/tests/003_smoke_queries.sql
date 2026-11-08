-- Useful inspection after seeding; produces demo score rows.
SELECT u.display_name, rss.total_marks, rss.breakdown,
       sv.version_no AS scheme_version, sm.mode_code, rr.release_no
FROM result_student_scores rss
JOIN result_releases rr ON rr.id=rss.release_id
JOIN review_roster_members rm ON rm.id=rss.roster_member_id
JOIN users u ON u.id=rm.student_user_id
JOIN scheme_versions sv ON sv.id=rr.scheme_version_id
JOIN scheme_modes sm ON sm.id=rr.scheme_mode_id
ORDER BY u.display_name;
SELECT 'schema-and-seed' AS component, count(*) AS number_of_tables
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE';
