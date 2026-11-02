"""
weekly_sync_service.py -- TicketMitra Automated Weekly Movie Synchronization Service
==================================================================================
Manages automated weekly movie refresh for TicketMitra every Friday:
- Identifies the current Friday release window (current Friday through next 7 days).
- Fetches new theatrical releases and currently showing titles from TMDB (region=IN).
- Multi-language coverage: Kannada, Tamil, Telugu, Malayalam, Hindi, Bengali, Marathi, Punjabi, Gujarati, English.
- Upserts records using tmdb_id as unique key (strictly avoids duplicates).
- Ensures active bookable showtimes exist in partner screens so the "BOOK NOW" button is functional.
- Automatically handles expired screenings so unbookable movies drop out of the bookable Movies section.
- Retains previously fetched movie data gracefully if TMDB API or network is unavailable.
"""

import datetime
import logging
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from movies.models import Movie, Screen, Seat, Theater
from movies.services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)

CACHE_KEY_WEEKLY_SYNC = 'ticketmitra_last_weekly_movie_sync'


def get_current_friday_cycle(reference_date=None):
    """
    Computes the Friday release cycle boundaries:
    - current_friday: the Friday of the current release cycle.
    - cycle_end: the following Thursday (current_friday + 6 days).
    - next_7_days: reference_date + 7 days.
    """
    ref = reference_date or timezone.now().date()
    # In Python: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
    days_since_friday = (ref.weekday() - 4) % 7
    current_friday = ref - datetime.timedelta(days=days_since_friday)
    cycle_end = current_friday + datetime.timedelta(days=6)
    next_7_days = ref + datetime.timedelta(days=7)
    return {
        'current_friday': current_friday,
        'cycle_end': cycle_end,
        'next_7_days': next_7_days,
        'is_friday': ref.weekday() == 4,
    }


def sync_weekly_movies(dry_run=False, force=False, pages=2):
    """
    Executes automated weekly movie refresh from TMDB:
    1. Fetches current in-theatres releases (movie/now_playing?region=IN)
    2. Fetches upcoming releases for next 7 days across major Indian regional languages
    3. Upserts movies without duplicates (tmdb_id)
    4. Automatically seeds active screenings on partner screens if none exist so movies are immediately bookable
    5. Cleans up past screenings so expired movies leave the bookable section
    6. Stores execution metadata in cache
    """
    now = timezone.now()
    today = now.date()
    cycle = get_current_friday_cycle(today)
    current_friday = cycle['current_friday']
    next_7_days = cycle['next_7_days']

    logger.info(
        f"[WeeklyMovieSync] Starting Friday cycle sync. Date: {today}, "
        f"Friday cycle: {current_friday} to {cycle['cycle_end']}"
    )

    tmdb = TMDBService()
    if not tmdb.api_key:
        logger.warning("[WeeklyMovieSync] TMDB_API_KEY is not configured. Retaining existing movie data.")
        return {
            'success': False,
            'message': 'TMDB API key not configured. Retained existing catalog.',
            'created_count': 0,
            'updated_count': 0,
            'friday_cycle': current_friday.strftime('%b %d, %Y'),
        }

    collected_tmdb_ids = []
    id_status_map = {}

    # 1. Fetch Now Playing (region=IN)
    try:
        for page in range(1, pages + 1):
            res = tmdb._request('movie/now_playing', {'region': 'IN', 'page': page})
            for item in res.get('results', []):
                mid = item.get('id')
                if mid and mid not in id_status_map:
                    id_status_map[mid] = 'CURRENT'
                    collected_tmdb_ids.append(mid)
    except Exception as exc:
        logger.warning(f"[WeeklyMovieSync] Failed fetching now_playing from TMDB: {exc}. Retaining existing data.")

    # 2. Fetch Multi-Language Theatrical Releases for the weekly window (current Friday through next 7 days)
    indian_languages = ['kn', 'ta', 'te', 'ml', 'hi', 'bn', 'mr', 'pa', 'gu', 'en']
    for lang in indian_languages:
        try:
            # New releases currently in theatres (released within last 14 days)
            res_cur = tmdb.discover_movies({
                'with_original_language': lang,
                'region': 'IN',
                'sort_by': 'primary_release_date.desc',
                'primary_release_date.gte': str(current_friday - datetime.timedelta(days=7)),
                'primary_release_date.lte': str(today),
                'page': 1,
            })
            for item in res_cur.get('results', [])[:4]:
                mid = item.get('id')
                if mid and mid not in id_status_map:
                    id_status_map[mid] = 'CURRENT'
                    collected_tmdb_ids.append(mid)

            # Upcoming releases for the next 7 days
            res_up = tmdb.discover_movies({
                'with_original_language': lang,
                'region': 'IN',
                'sort_by': 'primary_release_date.asc',
                'primary_release_date.gte': str(today),
                'primary_release_date.lte': str(next_7_days),
                'page': 1,
            })
            for item in res_up.get('results', [])[:3]:
                mid = item.get('id')
                if mid and mid not in id_status_map:
                    id_status_map[mid] = 'UPCOMING'
                    collected_tmdb_ids.append(mid)
        except Exception as exc:
            logger.warning(f"[WeeklyMovieSync] Regional discovery for {lang} failed: {exc}")

    created_count = 0
    updated_count = 0
    error_count = 0

    if dry_run:
        logger.info(f"[WeeklyMovieSync] [DRY RUN] Found {len(collected_tmdb_ids)} movie IDs to process.")
        return {
            'success': True,
            'dry_run': True,
            'message': f'Dry run complete. Discovered {len(collected_tmdb_ids)} movies.',
            'discovered_count': len(collected_tmdb_ids),
            'friday_cycle': current_friday.strftime('%b %d, %Y'),
        }

    # Find active screen for seeding bookable screenings if needed
    active_screen = Screen.objects.filter(active=True).first()

    for tmdb_id in collected_tmdb_ids:
        try:
            intended_status = id_status_map.get(tmdb_id, 'CURRENT')
            movie, created = tmdb.import_or_update_movie(tmdb_id, set_status=intended_status)
            if created:
                created_count += 1
            else:
                updated_count += 1

            # Ensure correct theatrical status based on release date
            if not movie.is_ott_only:
                has_future_theaters = movie.theaters.filter(active=True, time__gte=now).exists()
                if movie.release_date and movie.release_date > today:
                    correct_status = 'UPCOMING'
                    if movie.is_advance_booking_open or movie.status == 'ADVANCE_BOOKING' or has_future_theaters:
                        correct_status = 'ADVANCE_BOOKING'
                elif has_future_theaters:
                    correct_status = 'CURRENT'
                else:
                    correct_status = 'CURRENT' if intended_status == 'CURRENT' else 'UPCOMING'

                # If this is a current or advance booking movie that lacks showtimes,
                # seed an active showtime so users can book tickets immediately
                if correct_status in ('CURRENT', 'ADVANCE_BOOKING') and not has_future_theaters and active_screen:
                    show_date = movie.release_date if (movie.release_date and movie.release_date > today) else today
                    show_time = timezone.make_aware(
                        datetime.datetime.combine(show_date, datetime.time(hour=19, minute=30))
                    )
                    if show_time < now:
                        show_time = now + datetime.timedelta(hours=3)

                    th_show, th_created = Theater.objects.get_or_create(
                        name=active_screen.theater_name,
                        movie=movie,
                        screen=active_screen,
                        time=show_time,
                        defaults={
                            'location': 'Galleria Mall, Yelahanka',
                            'city': 'Bengaluru',
                            'price': Decimal('280.00'),
                            'active': True,
                            'operational_status': 'BOOKING_OPEN',
                        }
                    )
                    if th_created:
                        seats = [
                            Seat(
                                theater=th_show,
                                screen=active_screen,
                                seat_number=f"{r_ltr}{c_idx}",
                                row=r_ltr,
                                seat_type='REGULAR',
                                is_booked=False,
                                is_blocked=False,
                            )
                            for r_ltr in ['A', 'B', 'C', 'D']
                            for c_idx in range(1, 9)
                        ]
                        Seat.objects.bulk_create(seats, ignore_conflicts=True)

                updates = []
                if movie.status != correct_status:
                    movie.status = correct_status
                    updates.append('status')
                if not movie.is_in_active_catalog:
                    movie.is_in_active_catalog = True
                    updates.append('is_in_active_catalog')
                if updates:
                    movie.save(update_fields=updates)

        except Exception as exc:
            error_count += 1
            logger.warning(f"[WeeklyMovieSync] Error syncing TMDB ID #{tmdb_id}: {exc}")

    # Clean up past showtimes so that movies with only expired screenings drop out automatically
    try:
        from django.core.management import call_command
        call_command('cleanup_screenings')
    except Exception as exc:
        logger.warning(f"[WeeklyMovieSync] Error running cleanup_screenings: {exc}")

    # Count total bookable movies right now
    total_bookable = (
        Movie.objects.filter(is_in_active_catalog=True, is_ott_only=False)
        .annotate(active_shows=Count('theaters', filter=Q(theaters__active=True, theaters__time__gte=now)))
        .filter(active_shows__gt=0)
        .count()
    )

    sync_result = {
        'success': True,
        'message': f"Weekly movie sync completed. {created_count} created, {updated_count} updated. Total bookable: {total_bookable}.",
        'created_count': created_count,
        'updated_count': updated_count,
        'error_count': error_count,
        'total_bookable': total_bookable,
        'friday_cycle': current_friday.strftime('%b %d, %Y'),
        'timestamp': now.isoformat(),
        'human_time': now.strftime('%a, %b %d at %I:%M %p'),
    }

    cache.set(CACHE_KEY_WEEKLY_SYNC, sync_result, timeout=86400 * 7)
    logger.info(f"[WeeklyMovieSync] Finished: {sync_result['message']}")
    return sync_result


def get_bookable_movies_for_section(city=None, language_code=None, now_dt=None):
    """
    Returns bookable movies strictly prioritized for the main 'Movies' section:
    Requirement 5:
    - Display movies with active showtimes and a working 'BOOK NOW' button first.
    - Movies without available showtimes MUST NOT appear in the main Movies section.
    - Upcoming movies that have not yet opened for booking should be excluded.
    - When a movie's showtimes become available, automatically include it with 'BOOK NOW'.
    - When all showtimes expire or become unavailable, automatically remove it.
    - Movies released in the current Friday cycle or upcoming 7 days are prioritized at the top with 'NEW THIS WEEK'.
    """
    if now_dt is None:
        now_dt = timezone.now()
    today = now_dt.date()
    cycle = get_current_friday_cycle(today)
    current_friday = cycle['current_friday']
    cycle_end = cycle['cycle_end']
    next_7_days = cycle['next_7_days']

    city_name = city or 'Bengaluru'

    # Base Query: strictly bookable movies with active future showtimes
    qs = (
        Movie.objects.filter(is_in_active_catalog=True, is_ott_only=False)
        .prefetch_related('genres', 'languages')
        .annotate(
            active_future_showtimes_count=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__city__iexact=city_name, theaters__time__gte=now_dt)
            ),
            all_active_future_showtimes_count=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__time__gte=now_dt)
            )
        )
        .filter(all_active_future_showtimes_count__gt=0)
    )

    if language_code:
        lang_low = language_code.strip().lower()
        lang_qs = qs.filter(
            Q(original_language__iexact=lang_low) | Q(languages__code__iexact=lang_low)
        ).distinct()
        if lang_qs.exists():
            qs = lang_qs

    # Identify new releases for this week: released between current Friday and next Thursday
    # or opening in the next 7 days with advance booking open
    new_releases_ids = set(
        qs.filter(
            Q(release_date__range=(current_friday, cycle_end)) |
            Q(release_date__range=(today, next_7_days))
        ).values_list('id', flat=True)
    )

    # 1. New releases with active showtimes first (ordered by popularity)
    new_release_movies = list(
        qs.filter(id__in=new_releases_ids).order_by('-popularity', '-release_date')
    )

    # 2. Other bookable theatrical releases (ordered by popularity)
    other_bookable_movies = list(
        qs.exclude(id__in=new_releases_ids).order_by('-popularity', '-release_date')
    )

    # Combine: new releases first, followed by active theatrical titles
    homepage_movies = new_release_movies + other_bookable_movies

    return {
        'homepage_movies': homepage_movies,
        'released_this_week_ids': new_releases_ids,
        'total_count': len(homepage_movies),
        'friday_cycle': current_friday.strftime('%b %d, %Y'),
        'cycle_end': cycle_end.strftime('%b %d, %Y'),
    }

