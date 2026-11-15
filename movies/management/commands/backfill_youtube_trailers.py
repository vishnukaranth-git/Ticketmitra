from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from movies.tasks import backfill_movie_trailers_task


class Command(BaseCommand):
    help = 'Find and validate official YouTube trailers for existing movies that do not have one.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help='Limit the number of movies processed.')
        parser.add_argument('--background', action='store_true', help='Queue the scan in Celery instead of running inline.')

    def handle(self, *args, **options):
        limit = options['limit']
        if limit is not None and limit < 1:
            raise CommandError('--limit must be a positive integer.')

        if options['background']:
            if str(getattr(settings, 'CELERY_BROKER_URL', 'memory://')).startswith('memory://'):
                raise CommandError('Background mode requires a configured Celery broker and worker.')
            task = backfill_movie_trailers_task.delay(limit=limit)
            self.stdout.write(self.style.SUCCESS(f'Queued trailer backfill task {task.id}.'))
            return

        result = backfill_movie_trailers_task(limit=limit)
        self.stdout.write(self.style.SUCCESS(
            f"Trailer scan complete: found trailers for {result['found']} of {result['attempted']} movies."
        ))
