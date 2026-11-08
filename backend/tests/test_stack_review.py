"""Focused regression probes from review of the existing PR stack."""
import os
from concurrent.futures import ThreadPoolExecutor
import threading

import psycopg

from test_team_api import api  # noqa: F401
from proposals.curriculum.test_contracts import active, prepared  # noqa: F401


def test_synopsis_file_lock_has_no_shared_to_exclusive_upgrade(api):  # noqa: F811
    # Both submission-item validation and this capability lock the same file.
    # Acquiring SHARE here permits two transactions to hold SHARE and then
    # deadlock when each item's trigger upgrades to UPDATE. The capability must
    # serialize at the strongest required lock before validation proceeds.
    started = threading.Event()
    finished = threading.Event()
    args = ('18000000-0000-4000-8000-000000000001',
            '15000000-0000-4000-8000-000000000001',
            '00000000-0000-4000-8000-000000000001')
    statement = 'SELECT public.smartpro_synopsis_locked_version(%s,%s,%s)'
    def second():
        with psycopg.connect(os.environ['DATABASE_URL']) as db:
            db.execute('SET ROLE smartpro_runtime')
            db.execute("SET lock_timeout='3s'")
            started.set()
            result = db.execute(statement, args).fetchone()[0]
            finished.set()
            return result
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(os.environ['DATABASE_URL']) as first:
            first.execute('SET ROLE smartpro_runtime')
            assert first.execute(statement, args).fetchone()[0] is not None
            future = pool.submit(second)
            assert started.wait(3)
            assert not finished.wait(0.3), 'competing verification acquired a shared file lock'
        assert future.result(timeout=5) is not None
