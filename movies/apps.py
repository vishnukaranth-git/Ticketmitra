import logging
import os
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class MoviesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'movies'

    def ready(self):
        """
        Start lightweight in-process background scheduler when Django dev server starts.

        This scheduler runs management commands in daemon threads so that:
          - Screenings are cleaned up every hour automatically
          - Movies are synced from TMDB every 24 hours automatically

        In production, use Celery Beat instead (see TMDB_SETUP.md).
        The scheduler only activates in the main Django process (not the reloader or
        management commands other than runserver).
        """
        # Only run in the main worker process of the Django dev server
        # RUN_MAIN=true is set by Django's autoreloader for the actual server process
        if os.environ.get('RUN_MAIN') != 'true':
            return

        # Don't run scheduler when invoked via management commands (other than runserver)
        argv0 = os.path.basename(sys.argv[0]) if sys.argv else ''
        if argv0 in ('manage.py', 'django-admin', 'django-admin.py'):
            if len(sys.argv) > 1 and sys.argv[1] not in ('runserver',):
                return

        self._start_background_scheduler()

    def _start_background_scheduler(self):
        """Start daemon threads for periodic cleanup and TMDB sync tasks."""
        import threading

        def run_with_reschedule(command_name, command_args, interval_seconds, delay_seconds):
            """Runs a management command then reschedules itself."""
            def _task():
                try:
                    from django.core.management import call_command
                    logger.info(f"[Scheduler] Running {command_name}...")
                    call_command(command_name, *command_args)
                    logger.info(f"[Scheduler] {command_name} completed successfully.")
                except Exception as exc:
                    logger.error(f"[Scheduler] {command_name} failed: {exc}")
                finally:
                    # Reschedule after interval
                    timer = threading.Timer(interval_seconds, _task)
                    timer.daemon = True
                    timer.start()

            # Initial delayed start
            initial_timer = threading.Timer(delay_seconds, _task)
            initial_timer.daemon = True
            initial_timer.start()

        # Start screening cleanup: first run after 60s, then every 3600s (1 hour)
        run_with_reschedule(
            command_name='cleanup_screenings',
            command_args=[],
            interval_seconds=3600,
            delay_seconds=60,
        )

        # Start weekly Friday movie sync: runs periodically to ensure Friday releases are fresh
        run_with_reschedule(
            command_name='sync_weekly_movies',
            command_args=[],
            interval_seconds=14400,  # checks every 4 hours
            delay_seconds=180,       # initial run after 3 minutes
        )

        # Start TMDB sync: first run after 120s, then every 86400s (24 hours)
        run_with_reschedule(
            command_name='sync_tmdb_movies',
            command_args=['--all'],
            interval_seconds=86400,
            delay_seconds=120,
        )

        logger.info(
            "[TicketMitra Scheduler] Background scheduler started. "
            "cleanup_screenings: every 1h (first run in 60s). "
            "sync_weekly_movies: every 4h (first run in 180s). "
            "sync_tmdb_movies: every 24h (first run in 120s)."
        )
