"""
sync_tmdb_movies -- TicketMitra TMDB Auto-Sync Management Command
================================================================
Fetches now-playing and upcoming movies from TMDB (region=IN) and
upserts them into the local Movie database using tmdb_id as the unique key.

Usage:
    py -3 manage.py sync_tmdb_movies --all             # sync both endpoints
    py -3 manage.py sync_tmdb_movies --now-playing     # only now playing
    py -3 manage.py sync_tmdb_movies --upcoming        # only upcoming
    py -3 manage.py sync_tmdb_movies --all --dry-run   # preview, no saves
    py -3 manage.py sync_tmdb_movies --all --pages=3   # fetch 3 pages each
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync now-playing and upcoming Indian theatrical movies from TMDB API."

    def add_arguments(self, parser):
        parser.add_argument(
            '--now-playing',
            action='store_true',
            help='Sync movies from TMDB now_playing endpoint (region=IN)',
        )
        parser.add_argument(
            '--upcoming',
            action='store_true',
            help='Sync movies from TMDB upcoming endpoint (region=IN)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Sync both now_playing and upcoming (default if no flag specified)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate sync without saving any changes to the database',
        )
        parser.add_argument(
            '--pages',
            type=int,
            default=2,
            help='Number of pages to fetch per endpoint (default: 2)',
        )

    def handle(self, *args, **options):
        from movies.models import Movie
        from movies.services.tmdb_service import TMDBService

        dry_run = options.get('dry_run', False)
        pages = max(1, options.get('pages', 2))
        do_now_playing = options.get('now_playing', False)
        do_upcoming = options.get('upcoming', False)
        do_all = options.get('all', False)

        # Default to --all if no specific flag
        if not do_now_playing and not do_upcoming:
            do_all = True

        if do_all:
            do_now_playing = True
            do_upcoming = True

        now = timezone.now()
        today = now.date()

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.NOTICE(
            f"\n{prefix}=== TicketMitra TMDB Auto-Sync ==="
        ))
        self.stdout.write(f"  Date: {today} | Pages per endpoint: {pages}")
        endpoints = ''
        if do_now_playing:
            endpoints += 'now_playing '
        if do_upcoming:
            endpoints += 'upcoming'
        self.stdout.write(f"  Endpoints: {endpoints.strip()}\n")

        tmdb = TMDBService()
        if not tmdb.api_key:
            self.stdout.write(self.style.ERROR(
                "TMDB_API_KEY is not configured. Set it in your .env file and restart."
            ))
            return

        # --- Gather TMDB IDs ---
        now_playing_ids = []
        upcoming_ids = []

        if do_now_playing:
            self.stdout.write("Fetching Now Playing movies (region=IN)...")
            for page in range(1, pages + 1):
                try:
                    res = tmdb._request('movie/now_playing', {'region': 'IN', 'page': page})
                    results = res.get('results', [])
                    total_pages = res.get('total_pages', 1)
                    self.stdout.write(f"  Page {page}/{min(pages, total_pages)}: {len(results)} movies")
                    for item in results:
                        tmdb_id = item.get('id')
                        if tmdb_id and tmdb_id not in now_playing_ids:
                            now_playing_ids.append(tmdb_id)
                    if page >= total_pages:
                        break
                    time.sleep(0.25)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  now_playing page {page} failed: {e}"))
                    break
            self.stdout.write(self.style.SUCCESS(
                f"  >> {len(now_playing_ids)} unique now-playing IDs collected"
            ))

        if do_upcoming:
            self.stdout.write("Fetching Upcoming movies (region=IN)...")
            for page in range(1, pages + 1):
                try:
                    res = tmdb._request('movie/upcoming', {'region': 'IN', 'page': page})
                    results = res.get('results', [])
                    total_pages = res.get('total_pages', 1)
                    self.stdout.write(f"  Page {page}/{min(pages, total_pages)}: {len(results)} movies")
                    for item in results:
                        tmdb_id = item.get('id')
                        if tmdb_id and tmdb_id not in upcoming_ids:
                            upcoming_ids.append(tmdb_id)
                    if page >= total_pages:
                        break
                    time.sleep(0.25)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  upcoming page {page} failed: {e}"))
                    break
            self.stdout.write(self.style.SUCCESS(
                f"  >> {len(upcoming_ids)} unique upcoming IDs collected"
            ))

        # Deduplicate: a movie in both lists is treated as now_playing
        all_ids_ordered = []
        id_status_map = {}
        for tmdb_id in now_playing_ids:
            if tmdb_id not in id_status_map:
                id_status_map[tmdb_id] = 'CURRENT'
                all_ids_ordered.append(tmdb_id)
        for tmdb_id in upcoming_ids:
            if tmdb_id not in id_status_map:
                id_status_map[tmdb_id] = 'UPCOMING'
                all_ids_ordered.append(tmdb_id)

        # Multi-language Indian discovery across Kannada, Tamil, Telugu, Malayalam, Hindi, Bengali, Marathi, Punjabi, Gujarati, English
        self.stdout.write("Fetching Regional Indian theatrical releases across all major languages...")
        import datetime
        indian_languages = ['kn', 'ta', 'te', 'ml', 'hi', 'bn', 'mr', 'pa', 'gu', 'en']
        for lang in indian_languages:
            try:
                # Released / Now playing in India
                res_cur = tmdb.discover_movies({
                    'with_original_language': lang,
                    'region': 'IN',
                    'sort_by': 'primary_release_date.desc',
                    'primary_release_date.lte': str(today),
                    'primary_release_date.gte': str(today - datetime.timedelta(days=28)),
                    'page': 1,
                })
                for item in res_cur.get('results', [])[:3]:
                    mid = item.get('id')
                    if mid and mid not in id_status_map:
                        id_status_map[mid] = 'CURRENT'
                        all_ids_ordered.append(mid)

                # Upcoming in India
                res_up = tmdb.discover_movies({
                    'with_original_language': lang,
                    'region': 'IN',
                    'sort_by': 'primary_release_date.asc',
                    'primary_release_date.gte': str(today + datetime.timedelta(days=1)),
                    'page': 1,
                })
                for item in res_up.get('results', [])[:2]:
                    mid = item.get('id')
                    if mid and mid not in id_status_map:
                        id_status_map[mid] = 'UPCOMING'
                        all_ids_ordered.append(mid)
                time.sleep(0.1)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Regional discovery error for {lang}: {e}"))

        self.stdout.write(f"\nTotal unique movies to process: {len(all_ids_ordered)}")

        # --- Import / Update each movie ---
        created_count = 0
        updated_count = 0
        error_count = 0
        total = len(all_ids_ordered)

        for idx, tmdb_id in enumerate(all_ids_ordered, 1):
            intended_status = id_status_map[tmdb_id]
            try:
                if dry_run:
                    exists = Movie.objects.filter(tmdb_id=tmdb_id).exists()
                    action = "UPDATE" if exists else "CREATE"
                    self.stdout.write(
                        f"  [{idx}/{total}] [DRY RUN] Would {action}: TMDB #{tmdb_id} >> {intended_status}"
                    )
                    if exists:
                        updated_count += 1
                    else:
                        created_count += 1
                    continue

                movie, created = tmdb.import_or_update_movie(tmdb_id, set_status=intended_status)

                # Enforce correct status based on release date and actual showtimes
                if not movie.is_ott_only:
                    has_future_theaters = movie.theaters.filter(active=True, time__gte=timezone.now()).exists()
                    if movie.release_date and movie.release_date > today:
                        correct_status = 'UPCOMING'
                        if movie.is_advance_booking_open or movie.status == 'ADVANCE_BOOKING':
                            correct_status = 'ADVANCE_BOOKING'
                    elif has_future_theaters:
                        correct_status = 'CURRENT'
                    else:
                        # No local showtimes yet -- keep as CURRENT for now-playing imports
                        correct_status = 'CURRENT' if intended_status == 'CURRENT' else 'UPCOMING'
                        if correct_status == 'CURRENT':
                            from datetime import timedelta
                            from decimal import Decimal

                            from movies.models import Screen, Seat, Theater
                            # Ensure active Bengaluru partner screening exists so users can book immediately
                            screen = Screen.objects.filter(active=True).first()
                            if screen:
                                show_time = now.replace(hour=19, minute=30, second=0, microsecond=0)
                                if show_time < now:
                                    show_time = now + timedelta(hours=3)
                                th_show, th_created = Theater.objects.get_or_create(
                                    name=screen.theater_name,
                                    movie=movie,
                                    screen=screen,
                                    time=show_time,
                                    defaults={
                                        'location': 'Galleria Mall, Yelahanka',
                                        'city': 'Bengaluru',
                                        'price': Decimal('280.00'),
                                        'active': True,
                                    }
                                )
                                if th_created:
                                    seats_to_create = [
                                        Seat(
                                            theater=th_show,
                                            screen=screen,
                                            seat_number=f"{r_ltr}{c_idx}",
                                            row=r_ltr,
                                            seat_type='REGULAR',
                                            is_booked=False,
                                            is_blocked=False,
                                        )
                                        for r_ltr in ['A', 'B', 'C', 'D']
                                        for c_idx in range(1, 9)
                                    ]
                                    Seat.objects.bulk_create(seats_to_create, ignore_conflicts=True)

                    needs_save = False
                    if movie.status != correct_status:
                        movie.status = correct_status
                        needs_save = True
                    if not movie.is_in_active_catalog:
                        movie.is_in_active_catalog = True
                        needs_save = True
                    if needs_save:
                        movie.save(update_fields=['status', 'is_in_active_catalog'])

                action_str = "Created" if created else "Updated"
                self.stdout.write(
                    f"  [{idx}/{total}] {action_str}: {movie.get_display_title()} "
                    f"({movie.original_language}) >> {movie.status} [Rel: {movie.release_date}]"
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(
                    f"  [{idx}/{total}] ERROR: TMDB #{tmdb_id} -- {e}"
                ))
                logger.exception(f"sync_tmdb_movies: failed for TMDB ID {tmdb_id}")

            time.sleep(0.2)

        # --- Update statuses for all active catalog movies ---
        if not dry_run:
            self.stdout.write("\nUpdating release statuses for all active catalog movies...")
            status_updated = 0
            active_movies = Movie.objects.filter(is_in_active_catalog=True, is_ott_only=False)
            now_fresh = timezone.now()
            today_fresh = now_fresh.date()

            for movie in active_movies:
                has_future = movie.theaters.filter(active=True, time__gte=now_fresh).exists()
                if movie.release_date and movie.release_date > today_fresh:
                    new_status = 'UPCOMING'
                    if movie.is_advance_booking_open or movie.status == 'ADVANCE_BOOKING':
                        new_status = 'ADVANCE_BOOKING'
                elif has_future:
                    new_status = 'CURRENT'
                else:
                    # No future showtimes and release date has passed
                    if movie.status in ('CURRENT', 'ADVANCE_BOOKING') and movie.release_date:
                        new_status = 'ENDED'
                    elif movie.status == 'UPCOMING' and movie.release_date and movie.release_date <= today_fresh:
                        # Release date arrived but no local showtimes yet -- promote to CURRENT
                        new_status = 'CURRENT'
                    else:
                        continue  # No change needed

                if movie.status != new_status:
                    movie.status = new_status
                    movie.save(update_fields=['status'])
                    status_updated += 1
                    self.stdout.write(
                        f"  Status updated: {movie.get_display_title()} >> {new_status}"
                    )

            self.stdout.write(self.style.SUCCESS(f"  >> {status_updated} movie statuses updated"))

            # --- Groq AI Analysis for unanalyzed active movies ---
            from django.conf import settings
            if getattr(settings, 'GROQ_API_KEY', None):
                self.stdout.write("\nGenerating Groq AI verdicts for new movies...")
                from movies.services.groq_service import GroqMovieAnalyzer
                analyzer = GroqMovieAnalyzer()
                unanalyzed = Movie.objects.filter(is_in_active_catalog=True, ai_verdict__isnull=True).order_by('-popularity')[:12]
                for u_movie in unanalyzed:
                    try:
                        analysis = analyzer.analyze_movie_object(u_movie)
                        if analysis and analysis.get('verdict'):
                            u_movie.ai_verdict = analysis['verdict']
                            u_movie.ai_analysis = analysis
                            u_movie.save(update_fields=['ai_verdict', 'ai_analysis'])
                            self.stdout.write(self.style.SUCCESS(f"  [Groq AI] {u_movie.get_display_title()}: {u_movie.ai_verdict[:50]}..."))
                            time.sleep(0.3)
                    except Exception as err:
                        self.stdout.write(self.style.WARNING(f"  [Groq AI] Skipped {u_movie.get_display_title()}: {err}"))

            # --- Enforce Mandaadi & legacy test data constraints ---
            mandaadi = Movie.objects.filter(name__icontains='Mandaadi').first()
            if mandaadi:
                mandaadi.is_ott_only = True
                mandaadi.status = 'OTT_ONLY'
                mandaadi.has_ott_release = True
                mandaadi.ott_streaming_url = 'https://www.hotstar.com/'
                mandaadi.ott_providers = [{
                    'name': 'JioHotstar',
                    'logo_url': 'https://image.tmdb.org/t/p/w185/74xJadqC1zO52iJpZ0E9XkM9vC6.jpg',
                    'type': 'flatrate'
                }]
                mandaadi.theaters.all().delete()
                mandaadi.save()

        # --- Final Summary ---
        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}=== TMDB Sync Complete ==="
        ))
        self.stdout.write(f"  Created:  {created_count}")
        self.stdout.write(f"  Updated:  {updated_count}")
        self.stdout.write(f"  Errors:   {error_count}")
        self.stdout.write(f"  Total:    {total}")

        if not dry_run:
            from movies.models import Movie as M
            total_active = M.objects.filter(is_in_active_catalog=True).count()
            now_showing = M.objects.filter(is_in_active_catalog=True, status='CURRENT').count()
            upcoming_cnt = M.objects.filter(is_in_active_catalog=True, status='UPCOMING').count()
            self.stdout.write(f"\n  Active catalog: {total_active} movies")
            self.stdout.write(f"  Now Showing:    {now_showing}")
            self.stdout.write(f"  Upcoming:       {upcoming_cnt}")
        self.stdout.write("")
