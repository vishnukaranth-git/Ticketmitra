"""
cleanup_screenings -- TicketMitra Screening Lifecycle Management Command
=======================================================================
Deactivates past screenings (Theater objects) whose show time has passed,
then updates movie release statuses based on actual scheduling data.

SAFETY GUARANTEES:
  - NEVER deletes any Theater, Booking, or SeatReservation records.
  - Only sets Theater.active = False for past shows.
  - Only updates Movie.status -- never deletes movies.
  - Historical booking records remain fully intact.

Usage:
    py -3 manage.py cleanup_screenings          # live run
    py -3 manage.py cleanup_screenings --dry-run # preview only
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Deactivate past screenings and update movie release statuses from actual showtime data."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate cleanup without making any database changes',
        )

    def handle(self, *args, **options):
        from movies.models import Movie, SeatReservation, Theater

        dry_run = options.get('dry_run', False)
        now = timezone.now()
        prefix = '[DRY RUN] ' if dry_run else ''

        self.stdout.write(self.style.NOTICE(
            f"\n{prefix}=== TicketMitra Screening Cleanup ==="
        ))
        self.stdout.write(f"  Timestamp: {now.strftime('%Y-%m-%d %H:%M UTC')}\n")

        # -- 1. Deactivate past screenings -------------------------------------------
        past_active = Theater.objects.filter(active=True, time__lt=now)
        past_count = past_active.count()

        self.stdout.write(f"Past active screenings found: {past_count}")

        if past_count > 0:
            if dry_run:
                for th in past_active[:10]:
                    self.stdout.write(
                        f"  [DRY RUN] Would deactivate: {th.name} -- "
                        f"{th.movie.get_display_title()} @ {th.time.strftime('%Y-%m-%d %H:%M')}"
                    )
                if past_count > 10:
                    self.stdout.write(f"  ... and {past_count - 10} more")
            else:
                updated = past_active.update(active=False)
                self.stdout.write(self.style.SUCCESS(
                    f"  >> Deactivated {updated} past screening(s) (active set to False)"
                ))
                logger.info(f"cleanup_screenings: deactivated {updated} past screenings")
        else:
            self.stdout.write(self.style.SUCCESS("  >> No past active screenings to deactivate"))

        # -- 2. Update movie statuses from actual showtime data -----------------------
        self.stdout.write("\nUpdating movie release statuses...")

        movies_ended = 0
        movies_to_current = 0
        movies_to_upcoming = 0

        # Refresh timestamp after deactivation
        now_fresh = timezone.now()
        today_fresh = now_fresh.date()

        # Only process active catalog movies (not OTT-only, not DRAFT)
        candidate_movies = Movie.objects.filter(
            is_in_active_catalog=True,
            is_ott_only=False,
        ).exclude(status='DRAFT')

        for movie in candidate_movies:
            has_future_shows = movie.theaters.filter(active=True, time__gte=now_fresh).exists()

            if movie.release_date and movie.release_date > today_fresh:
                # Future release date -- must be UPCOMING or ADVANCE_BOOKING
                if movie.status in ('ADVANCE_BOOKING',) or movie.is_advance_booking_open:
                    target_status = 'ADVANCE_BOOKING'
                else:
                    target_status = 'UPCOMING'
            elif has_future_shows:
                # Has active upcoming screenings -- NOW SHOWING
                target_status = 'CURRENT'
            elif movie.status in ('CURRENT', 'ADVANCE_BOOKING'):
                # No future shows and release date has passed -- theatrical run ended
                target_status = 'ENDED'
            elif movie.status == 'UPCOMING' and movie.release_date and movie.release_date <= today_fresh:
                # Was upcoming, release date arrived, but no local shows yet -- keep visible
                target_status = 'CURRENT'
            else:
                # Status is already correct or movie is ENDED/OTT_ONLY
                continue

            if movie.status != target_status:
                old_status = movie.status
                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] Would update: {movie.get_display_title()} "
                        f"{old_status} >> {target_status}"
                    )
                else:
                    movie.status = target_status
                    movie.save(update_fields=['status'])
                    self.stdout.write(
                        f"  Updated: {movie.get_display_title()} {old_status} >> {target_status}"
                    )
                    logger.info(
                        f"cleanup_screenings: {movie.get_display_title()} "
                        f"{old_status} >> {target_status}"
                    )

                if target_status == 'ENDED':
                    movies_ended += 1
                elif target_status == 'CURRENT':
                    movies_to_current += 1
                elif target_status in ('UPCOMING', 'ADVANCE_BOOKING'):
                    movies_to_upcoming += 1

        # -- 3. Expire stale SeatReservations (ACTIVE but past expires_at) ----------
        # Safe: only updates status, never deletes records
        expired_reservations = SeatReservation.objects.filter(
            status='ACTIVE',
            expires_at__lt=now_fresh,
        )
        expired_res_count = expired_reservations.count()
        if expired_res_count > 0:
            if not dry_run:
                expired_reservations.update(status='EXPIRED')
                logger.info(f"cleanup_screenings: expired {expired_res_count} stale seat reservations")
            self.stdout.write(
                f"\n{'[DRY RUN] Would expire' if dry_run else 'Expired'} "
                f"{expired_res_count} stale seat reservation(s)"
            )

        # -- 4. Summary --------------------------------------------------------------
        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}=== Cleanup Complete ==="
        ))
        self.stdout.write(f"  Past screenings deactivated: {past_count if not dry_run else '(dry run)'}")
        self.stdout.write(f"  Movies moved to ENDED:       {movies_ended}")
        self.stdout.write(f"  Movies moved to CURRENT:     {movies_to_current}")
        self.stdout.write(f"  Movies moved to UPCOMING:    {movies_to_upcoming}")
        self.stdout.write(f"  Stale reservations expired:  {expired_res_count}")
        self.stdout.write("")
