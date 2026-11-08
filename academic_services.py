"""Framework-neutral, explicitly test-only publication policy and outbox protocol."""
from uuid import uuid4

from psycopg.types.json import Jsonb


def publish_single_evaluator_test(db, review_id, assessment_id, actor_id, reason=None):
    """Caller supplies a transaction. Unknown/multiple-source aggregation is rejected."""
    review = db.execute('SELECT * FROM project_reviews WHERE id=%s FOR UPDATE', (review_id,)).fetchone()
    if not review:
        raise ValueError('Unknown review')
    count = db.execute("SELECT count(*) AS n FROM assessments WHERE review_id=%s AND state='FINALIZED'", (review_id,)).fetchone()['n']
    if count != 1:
        raise ValueError('Multi-evaluator aggregation policy is not configured')
    previous = db.execute('SELECT * FROM result_releases WHERE review_id=%s ORDER BY release_no DESC LIMIT 1', (review_id,)).fetchone()
    rid = str(uuid4())
    db.execute('''INSERT INTO result_releases(id,review_id,release_no,scheme_version_id,scheme_mode_id,calculation_snapshot,
      released_by,supersedes_id,correction_reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
      (rid, review_id, previous['release_no'] + 1 if previous else 1, review['scheme_version_id'], review['scheme_mode_id'],
       Jsonb({'method': 'single_evaluator_sum', 'exampleOnly': True}), actor_id, previous['id'] if previous else None, reason))
    db.execute('INSERT INTO result_source_assessments(release_id,review_id,assessment_id) VALUES(%s,%s,%s)', (rid, review_id, assessment_id))
    team = db.execute('SELECT coalesce(sum(marks),0) AS n FROM team_criterion_scores WHERE assessment_id=%s', (assessment_id,)).fetchone()['n']
    for member in db.execute('SELECT * FROM review_roster_members WHERE review_id=%s ORDER BY id', (review_id,)).fetchall():
        individual = db.execute('SELECT coalesce(sum(marks),0) AS n FROM student_criterion_scores WHERE assessment_id=%s AND roster_member_id=%s',
                                (assessment_id, member['id'])).fetchone()['n']
        db.execute('''INSERT INTO result_student_scores(release_id,review_id,roster_member_id,total_marks,breakdown)
          VALUES(%s,%s,%s,%s,%s)''', (rid, review_id, member['id'], team + individual,
                                   Jsonb({'team': float(team), 'individual': float(individual)})))
    db.execute('UPDATE result_releases SET sealed_at=clock_timestamp() WHERE id=%s', (rid,))
    db.execute("UPDATE project_reviews SET review_state='RELEASED',row_version=row_version+1 WHERE id=%s", (review_id,))
    return rid


def claim_events(db, batch_size=10, lease_seconds=30):
    return db.execute('SELECT * FROM smartpro_claim_outbox(%s,%s)', (batch_size, lease_seconds)).fetchall()


def acknowledge_event(db, event_id, token):
    return db.execute('SELECT smartpro_ack_outbox(%s,%s) AS ok', (event_id, token)).fetchone()['ok']


def retry_event(db, event_id, token, error, max_attempts=5):
    return db.execute('SELECT smartpro_retry_outbox(%s,%s,%s,%s) AS ok', (event_id, token, error, max_attempts)).fetchone()['ok']


def record_local_notification(db, event, recipient, dedupe_key):
    """Idempotent database receipt only. No external provider delivery is claimed."""
    return db.execute('''INSERT INTO notification_deliveries(outbox_event_id,recipient_user_id,channel,dedupe_key)
      VALUES(%s,%s,'IN_APP',%s) ON CONFLICT(dedupe_key) DO NOTHING RETURNING id''',
      (event, recipient, dedupe_key)).fetchone()
