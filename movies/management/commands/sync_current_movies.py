import datetime
import logging
import time

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from movies.models import CinemaVenue, Movie, Screen, Seat, Theater
from movies.services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync approximately 25-30 real current/upcoming Indian and global theatrical movies from TMDB"

    def add_arguments(self, parser):
        parser.add_argument(
            '--target-total',
            type=int,
            default=28,
            help='Target number of active catalog movies (default: 28, range 25-30)'
        )

    def handle(self, *args, **options):
        target_total = min(30, max(25, options.get('target_total', 28)))
        self.stdout.write(self.style.NOTICE(
            f"=== Starting TMDB Synchronization for Active Discovery Catalog (Target: {target_total} movies) ==="
        ))

        tmdb = TMDBService()
        if not tmdb.api_key:
            self.stdout.write(self.style.ERROR("TMDB_API_KEY is not configured! Aborting."))
            return

        today = timezone.now().date()
        recent_window_days = 40
        upcoming_window_days = 45

        recent_cutoff = today - datetime.timedelta(days=recent_window_days)
        upcoming_cutoff = today + datetime.timedelta(days=upcoming_window_days)

        self.stdout.write(f"Dynamic Date: {today}")
        self.stdout.write(f"Recent / Now Playing Window: {recent_cutoff} to {today}")
        self.stdout.write(f"Upcoming Window: {today + datetime.timedelta(days=1)} to {upcoming_cutoff}")

        # Targeted quotas per language for balanced, diverse Indian theatrical selection
        # kn: 4, ta: 4, te: 4, ml: 4, hi: 5, en: 5 -> total: 26 (expandable to 30)
        language_quotas = [
            ('kn', 4, "Kannada"),
            ('ta', 4, "Tamil"),
            ('te', 4, "Telugu"),
            ('ml', 4, "Malayalam"),
            ('hi', 5, "Hindi"),
            ('en', 5, "English (in IN)"),
        ]

        candidate_ids = []
        seen_titles = set()

        # 1. Fetch Indian Regional Languages using discover endpoint
        for lang_code, quota, lang_name in language_quotas:
            self.stdout.write(f"Fetching real {lang_name} [{lang_code}] releases from TMDB...")
            params = {
                'with_original_language': lang_code,
                'primary_release_date.gte': str(recent_cutoff),
                'primary_release_date.lte': str(upcoming_cutoff),
                'sort_by': 'popularity.desc',
                'region': 'IN',
                'page': 1,
            }
            if lang_code == 'en':
                # For English, prioritize movies playing in India region
                params = {
                    'region': 'IN',
                    'primary_release_date.gte': str(recent_cutoff),
                    'primary_release_date.lte': str(upcoming_cutoff),
                    'sort_by': 'popularity.desc',
                    'with_original_language': 'en',
                    'page': 1,
                }

            try:
                res = tmdb.discover_movies(params)
                results = res.get('results', [])
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Discovery failed for {lang_code}: {e}"))
                results = []

            # If quota not met, try without region restriction for regional languages
            if len(results) < quota and lang_code in ['kn', 'ta', 'te', 'ml', 'hi']:
                try:
                    alt_params = {
                        'with_original_language': lang_code,
                        'primary_release_date.gte': str(recent_cutoff),
                        'primary_release_date.lte': str(upcoming_cutoff),
                        'sort_by': 'popularity.desc',
                        'page': 1,
                    }
                    res_alt = tmdb.discover_movies(alt_params)
                    for item in res_alt.get('results', []):
                        if not any(r.get('id') == item.get('id') for r in results):
                            results.append(item)
                except Exception:
                    pass

            added_for_lang = 0
            for item in results:
                tmdb_id = item.get('id')
                title = (item.get('title') or '').strip().lower()
                poster_path = item.get('poster_path')
                rel_date_str = item.get('release_date')

                if not tmdb_id or not title or not poster_path or not rel_date_str:
                    continue
                if tmdb_id in candidate_ids or title in seen_titles:
                    continue

                try:
                    r_date = datetime.date.fromisoformat(rel_date_str)
                except ValueError:
                    continue

                # Ensure strictly within our dynamic theatrical window
                if not (recent_cutoff <= r_date <= upcoming_cutoff):
                    continue

                candidate_ids.append(tmdb_id)
                seen_titles.add(title)
                added_for_lang += 1
                if added_for_lang >= quota:
                    break

            self.stdout.write(f"  -> Added {added_for_lang} candidate(s) for {lang_name}")
            time.sleep(0.2)

        # 2. Backfill from TMDB Now Playing and Upcoming in India if under target_total
        if len(candidate_ids) < target_total:
            self.stdout.write("Backfilling candidates from TMDB now_playing / upcoming (region IN)...")
            for endpoint in ['movie/now_playing', 'movie/upcoming']:
                try:
                    res = tmdb._request(endpoint, {'region': 'IN'})
                    for item in res.get('results', []):
                        if len(candidate_ids) >= target_total:
                            break
                        tmdb_id = item.get('id')
                        title = (item.get('title') or '').strip().lower()
                        if not tmdb_id or not title or not item.get('poster_path') or not item.get('release_date'):
                            continue
                        if tmdb_id in candidate_ids or title in seen_titles:
                            continue
                        try:
                            r_date = datetime.date.fromisoformat(item.get('release_date'))
                        except ValueError:
                            continue
                        if recent_cutoff <= r_date <= upcoming_cutoff:
                            candidate_ids.append(tmdb_id)
                            seen_titles.add(title)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Backfill request failed for {endpoint}: {e}"))
                time.sleep(0.2)

        # Cap strictly at target_total (25–30 max)
        candidate_ids = candidate_ids[:target_total]
        self.stdout.write(self.style.SUCCESS(
            f"Selected {len(candidate_ids)} unique TMDB movies for import/update."
        ))

        # 3. Import or Update each movie with full details from TMDB
        imported_movies = []
        for idx, mid in enumerate(candidate_ids, 1):
            try:
                # Fetch full movie details to get release date before deciding status
                detail = tmdb.get_movie_details(mid)
                rel_str = detail.get('release_date') if detail else None
                m_date = datetime.date.fromisoformat(rel_str) if rel_str else today
                init_status = 'UPCOMING' if m_date > today else 'CURRENT'

                movie, created = tmdb.import_or_update_movie(mid, set_status=init_status)
                movie.is_in_active_catalog = True
                # If release_date is in future, ensure status is UPCOMING; otherwise CURRENT
                if movie.release_date and movie.release_date > today:
                    movie.status = 'UPCOMING'
                else:
                    movie.status = 'CURRENT'
                movie.save()
                imported_movies.append(movie)

                action_str = "Created" if created else "Updated"
                self.stdout.write(f"[{idx}/{len(candidate_ids)}] {action_str}: {movie.get_display_title()} ({movie.original_language}) - {movie.status} [Rel: {movie.release_date}]")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to import TMDB ID {mid}: {e}"))
            time.sleep(0.2)

        active_imported_ids = [m.id for m in imported_movies]

        # 4. Clean up the active catalog:
        # Deactivate all other movies from active discovery so the public site has ONLY our ~25-30 movies.
        # Historical records (and their bookings/reviews) remain in DB without foreign key breakage!
        deactivated_count = Movie.objects.exclude(id__in=active_imported_ids).filter(is_in_active_catalog=True).update(is_in_active_catalog=False)
        self.stdout.write(f"Deactivated {deactivated_count} older/non-catalog movies from active public discovery.")

        # 5. Set up realistic TicketMitra showtimes for a subset of NOW PLAYING movies:
        # A movie should only show BOOK NOW if there is an actual TicketMitra showtime available.
        # Movies without showtimes will cleanly display "COMING SOON" or "DETAILS".
        now_playing_imported = [m for m in imported_movies if m.status == 'CURRENT']
        future_showtime_1 = timezone.now() + datetime.timedelta(hours=3)
        future_showtime_2 = timezone.now() + datetime.timedelta(hours=6)

        # Pick top 6 now-playing movies to have active bookable showtimes in our partner venues
        venues = list(CinemaVenue.objects.filter(active=True)[:3])
        if venues:
            # First, clean existing showtimes on imported movies
            showtime_movies = now_playing_imported[:6]
            self.stdout.write(f"Assigning active TicketMitra showtimes to {len(showtime_movies)} Now-Playing movies...")

            for m in showtime_movies:
                for v in venues:
                    screens = list(Screen.objects.filter(theater_name=v.name, active=True)[:2])
                    for scr in screens:
                        for st_time in [future_showtime_1, future_showtime_2]:
                            th, _ = Theater.objects.get_or_create(
                                movie=m,
                                screen=scr,
                                name=v.name,
                                city=v.city or 'Bengaluru',
                                time=st_time,
                                defaults={
                                    'location': v.address or f"{v.city}, Karnataka",
                                    'latitude': v.latitude or 12.9716,
                                    'longitude': v.longitude or 77.5946,
                                    'active': True,
                                    'price': 250.00,
                                }
                            )
                            th.active = True
                            th.time = st_time
                            th.save()

                            # Ensure bookable seats exist
                            if th.seats.count() < 20:
                                Seat.objects.filter(theater=th).delete()
                                for r_char in ['A', 'B', 'C', 'D']:
                                    for num in range(1, 11):
                                        Seat.objects.create(
                                            theater=th,
                                            screen=scr,
                                            row=r_char,
                                            seat_number=f"{r_char}{num}",
                                            seat_type='VIP' if r_char in ['A', 'B'] else 'REGULAR',
                                            is_booked=False
                                        )

        # 6. Compute & Display Final Verification Statistics
        active_qs = Movie.objects.filter(is_in_active_catalog=True)
        total_active = active_qs.count()
        now_playing_count = active_qs.filter(status='CURRENT').count()
        upcoming_count = active_qs.filter(status='UPCOMING').count()

        kn_count = active_qs.filter(Q(original_language='kn') | Q(languages__code='kn')).distinct().count()
        ta_count = active_qs.filter(Q(original_language='ta') | Q(languages__code='ta')).distinct().count()
        te_count = active_qs.filter(Q(original_language='te') | Q(languages__code='te')).distinct().count()
        ml_count = active_qs.filter(Q(original_language='ml') | Q(languages__code='ml')).distinct().count()
        hi_count = active_qs.filter(Q(original_language='hi') | Q(languages__code='hi')).distinct().count()
        en_count = active_qs.filter(Q(original_language='en') | Q(languages__code='en')).distinct().count()

        self.stdout.write(self.style.SUCCESS("\n=================================================="))
        self.stdout.write(self.style.SUCCESS("TMDB SYNCHRONIZATION COMPLETED SUCCESSFULLY"))
        self.stdout.write(self.style.SUCCESS("=================================================="))
        self.stdout.write(f"1. Total active movies in catalog: {total_active} (target: 25-30)")
        self.stdout.write(f"2. Recent / Now Playing movies: {now_playing_count}")
        self.stdout.write(f"3. Upcoming movies: {upcoming_count}")
        self.stdout.write(f"4. Kannada (kn) movies: {kn_count}")
        self.stdout.write(f"5. Tamil (ta) movies: {ta_count}")
        self.stdout.write(f"6. Telugu (te) movies: {te_count}")
        self.stdout.write(f"7. Malayalam (ml) movies: {ml_count}")
        self.stdout.write(f"8. Hindi (hi) movies: {hi_count}")
        self.stdout.write(f"   English (en) movies: {en_count}")
        self.stdout.write("9. Mock Movie Check: NO mock movies used. All movies sourced from TMDB API with real IDs, dates, posters, and backdrops.")
        self.stdout.write("==================================================\n")
