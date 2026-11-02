"""
sync_weekly_movies.py -- TicketMitra Friday Movie Sync Management Command
========================================================================
Synchronizes the latest Indian theatrical movies from TMDB for the Friday release
cycle and ensures all movies appearing in the main Movies section are bookable.

Usage:
    py -3 manage.py sync_weekly_movies              # sync current Friday releases
    py -3 manage.py sync_weekly_movies --force      # ignore cache and force sync
    py -3 manage.py sync_weekly_movies --dry-run    # preview discovered movies
    py -3 manage.py sync_weekly_movies --pages=3    # fetch 3 pages
"""

from django.core.management.base import BaseCommand
from movies.services.weekly_sync_service import sync_weekly_movies, get_current_friday_cycle


class Command(BaseCommand):
    help = "Synchronizes weekly Friday theatrical movie releases from TMDB (region=IN)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force a full synchronization regardless of previous sync status',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate discovery without making changes to the database',
        )
        parser.add_argument(
            '--pages',
            type=int,
            default=2,
            help='Number of pages to query per endpoint (default: 2)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        pages = max(1, options.get('pages', 2))

        cycle = get_current_friday_cycle()
        prefix = '[DRY RUN] ' if dry_run else ''

        self.stdout.write(self.style.NOTICE(
            f"\n{prefix}=== TicketMitra Friday Movie Sync ==="
        ))
        self.stdout.write(
            f"  Friday Cycle: {cycle['current_friday'].strftime('%a, %b %d, %Y')} "
            f"through {cycle['cycle_end'].strftime('%a, %b %d, %Y')}"
        )
        self.stdout.write(f"  Pages per endpoint: {pages} | Force: {force}\n")

        result = sync_weekly_movies(dry_run=dry_run, force=force, pages=pages)

        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f"[SUCCESS] {result.get('message')}"
            ))
            if not dry_run:
                self.stdout.write(
                    f"  Created: {result.get('created_count', 0)} | "
                    f"Updated: {result.get('updated_count', 0)} | "
                    f"Total Bookable: {result.get('total_bookable', 0)}"
                )
        else:
            self.stdout.write(self.style.WARNING(
                f"[WARNING] {result.get('message')}"
            ))

