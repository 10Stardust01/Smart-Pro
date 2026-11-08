"""Deterministic in-app checks; no external delivery or academic data seeding."""
import os
import signal
import threading

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection, DatabaseError


class Command(BaseCommand):
    help='Generate and resolve notifications from configured course deadlines'

    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
        parser.add_argument('--interval',type=int,default=60)

    def handle(self,*args,**options):
        if os.getenv('SMARTPRO_COURSE_API')!='YES' or os.getenv('SMARTPRO_ACADEMIC_API')!='YES':
            raise CommandError('Course notifications are disabled')
        if not 15<=options['interval']<=3600:raise CommandError('Use a check interval of 15–3600 seconds')
        stop=threading.Event()
        signal.signal(signal.SIGTERM,lambda *_:stop.set())
        signal.signal(signal.SIGINT,lambda *_:stop.set())
        while not stop.is_set():
            try:
                close_old_connections()
                with connection.cursor() as cursor:
                    cursor.execute('SELECT public.smartpro_dispatch_course_notifications()')
                    result=cursor.fetchone()[0]
                self.stdout.write(str(result))
            except DatabaseError:
                if options['once']:raise CommandError('Notification check failed; no external delivery is implied') from None
                self.stderr.write('Course notification check failed; the next scheduled pass will retry')
            finally:connection.close()
            if options['once']:return
            stop.wait(options['interval'])
