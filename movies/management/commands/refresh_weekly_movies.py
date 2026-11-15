"""
refresh_weekly_movies.py -- TicketMitra Automated Weekly Movie Refresh Management Command
========================================================================================
Runs the weekly theatrical movie refresh for Thursday & Friday release cycles:
- Discovers newly released theatrical movies and verifies theatrical release dates.
- Refreshes movie listings and release classifications across the website.
- Ensures all participating theatres have valid showtimes (>=3 for multistarrers, >=1 for standard).
- Expires outdated showtimes safely without touching existing bookings.
- Idempotent and safe for repeated execution.
"""

from django.core.management.base import BaseCommand
from movies.services.weekly_sync_service import sync_weekly_movies, get_current_friday_cycle
from movies.services.schedule_service import generate_schedule_for_cinema_network


class Command(BaseCommand):
    help = "Execute the TicketMitra weekly movie refresh and network showtime generation (Thursday & Friday)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force a full synchronization regardless of cache status',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate discovery and showtime generation without making database changes',
        )
        parser.add_argument(
            '--pages',
            type=int,
            default=2,
            help='Number of TMDB pages to query per language endpoint (default: 2)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        pages = max(1, options.get('pages', 2))

        cycle = get_current_friday_cycle()
        prefix = '[DRY RUN] ' if dry_run else ''

        self.stdout.write(self.style.NOTICE(
            f"\n{prefix}=== TicketMitra Weekly Movie Refresh & Schedule Generation ==="
        ))
        self.stdout.write(
            f"  Release Cycle: {cycle['current_friday'].strftime('%a, %b %d, %Y')} "
            f"through {cycle['cycle_end'].strftime('%a, %b %d, %Y')}"
        )

        result = sync_weekly_movies(dry_run=dry_run, force=force, pages=pages)

        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f"[SUCCESS] {result.get('message')}"
            ))
            if not dry_run:
                self.stdout.write(
                    f"  Created Movies: {result.get('created_count', 0)} | "
                    f"Updated Movies: {result.get('updated_count', 0)} | "
                    f"Total Bookable: {result.get('total_bookable', 0)}"
                )
        else:
            self.stdout.write(self.style.WARNING(
                f"[WARNING] {result.get('message')}"
            ))

