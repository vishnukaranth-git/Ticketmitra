"""
ranking_service.py -- TicketMitra Intelligent Movie Ranking & Demand Prioritization Service
========================================================================================
Implements dynamic movie demand scoring and categorization for the TicketMitra discovery page:
1. Demand Scoring Algorithm:
   - TMDB Popularity & rating metrics
   - Franchise / Sequel / Multistarrer / High-Demand indicators (e.g., Jailer 2, Ramayana, Drishyam, etc.)
   - Advance booking status (promotes movies when advance booking opens)
   - Real ticket booking velocity & confirmed booking counts
   - Active showtime density across cinema screens
   - Release date & theatrical window recency
2. Category Organization:
   - A. TRENDING & BOOKING OPEN (Most anticipated high-demand releases with active tickets)
   - B. UPCOMING ANTICIPATED MOVIES (Major upcoming theatrical productions, COMING SOON)
   - C. NOW SHOWING (All other current theatrical titles with active showtimes)
3. Strict Booking Enforcement:
   - Never display 'BOOK NOW' for movies without valid, active future showtimes
   - Upcoming movies without open showtimes strictly display 'COMING SOON'
   - When showtimes are added or advance booking opens, movies automatically promote
   - When showtimes expire, movies automatically drop from bookable rails
"""

import datetime
import logging
import re

from django.core.cache import cache
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from movies.models import CinemaVenue, Movie

logger = logging.getLogger(__name__)

CACHE_KEY_CATEGORIZED_MOVIES = 'ticketmitra_categorized_movies'
CACHE_KEY_RANKING_VERSION = 'ticketmitra_categorized_movies_version'
CACHE_TTL = 300  # 5 minutes cache for fast discovery

# Detect sequel/franchise signals without matching specific movie or country names.
FRANCHISE_PATTERN = re.compile(
    r'\b('
    r'part\s*\d+|chapter\s*\d+|volume\s*\d+|vol\.?\s*\d+|'
    r'\d+|conclusion|returns|reloaded|revolution|legacy|reborn|'
    r'finale|awakens|rises|revenge|resurrection|franchise'
    r')\b',
    re.IGNORECASE,
)


def calculate_movie_demand_score(movie, active_shows_count=0, bookings_count=0, today=None):
    """
    Computes an intelligent multi-factor demand and anticipation score.
    Higher score indicates greater audience demand and trending theatrical presence.
    """
    if today is None:
        today = timezone.now().date()

    # 1. Base popularity score from TMDB (scaled up to 140 pts)
    pop = float(movie.popularity or 0.0)
    score = min(pop, 400.0) * 0.35

    # 2. Franchise / Sequel / Big-Budget Epic detection (+40 pts)
    title = f"{movie.title or ''} {movie.name or ''} {movie.original_title or ''}".strip()
    is_franchise = bool(FRANCHISE_PATTERN.search(title))
    if is_franchise:
        score += 40.0

    try:
        if len(movie.cast_members.all()) >= 5:
            score += 15.0
    except Exception:
        pass

    # 3. Advance Booking Open Status (+35 pts)
    if movie.is_advance_booking_open or movie.status == 'ADVANCE_BOOKING':
        score += 35.0

    # 4. Active Showtimes Density across cinema screens (up to 35 pts)
    # The more screens screening this title, the higher the exhibitor and audience demand
    score += min(active_shows_count * 2.5, 35.0)

    # 5. Real Audience Ticket Sales & Booking Velocity (up to 35 pts)
    score += min(bookings_count * 5.0, 35.0)

    # 6. Verified booking demand only; ratings do not make a movie trending.

    return round(score, 1)


def get_movie_demand_badge(movie, is_franchise=False, is_bookable=False, today=None):
    """
    Returns an appropriate UI badge label for trending and anticipated movies.
    """
    today = today or timezone.now().date()
    if (movie.release_date and movie.release_date > today and movie.is_advance_booking_open and is_bookable):
        return 'ADVANCE OPEN'
    if is_franchise:
        return 'FRANCHISE'
    pop = float(movie.popularity or 0.0)
    if pop >= 80.0:
        return 'TRENDING'
    if pop >= 35.0:
        return 'HIGH DEMAND'
    if movie.release_date and (today - datetime.timedelta(days=14)) <= movie.release_date <= today:
        return 'NEW RELEASE'
    return None


def get_promotional_priority(movie):
    """Rank theatrical assets: official trailer plus multiple distinct posters leads."""
    trailer = bool((movie.trailer_url or '').strip())
    try:
        posters = {
            (p.image.name if p.image and getattr(p.image, 'name', '') else p.get_url())
            for p in movie.posters.all()
            if p.get_url()
        }
    except Exception:
        posters = set()
    direct_poster = ''
    if movie.image and getattr(movie.image, 'name', ''):
        direct_poster = movie.image.name
    elif movie.poster_url:
        direct_poster = movie.poster_url
    if direct_poster:
        posters.add(direct_poster)
    multiple_posters = len(posters) > 1
    if trailer and multiple_posters:
        return 0
    if trailer:
        return 1
    if multiple_posters:
        return 2
    return 3


def sort_movies_by_release_and_promotion(movies, *, newest_date_first=False):
    """Keep theatrical release dates together, then rank assets and audience demand."""
    date_key = lambda movie: movie.release_date or datetime.date.max
    movies.sort(key=lambda movie: (
        -date_key(movie).toordinal() if newest_date_first and movie.release_date else date_key(movie).toordinal(),
        get_promotional_priority(movie),
        -getattr(movie, 'calculated_demand_score', float(movie.popularity or 0)),
        -float(movie.popularity or 0),
        -float(movie.tmdb_rating or movie.rating or 0),
        (movie.title or movie.name or '').casefold(),
    ))
    return movies


def get_categorized_movies(city=None, language_code=None, now_dt=None, bypass_cache=False):
    """
    Retrieves and categorizes movies into the three requested categories:
    A. TRENDING & BOOKING OPEN (Most anticipated high-demand releases with active bookings)
    B. UPCOMING ANTICIPATED MOVIES (Major upcoming theatrical releases, COMING SOON)
    C. NOW SHOWING (Other running theatrical movies with active showtimes)
    """
    if now_dt is None:
        now_dt = timezone.now()
    today = now_dt.date()

    city_key = (city or 'all').lower()
    lang_key = (language_code or 'all').lower()
    try:
        ranking_version = cache.get(CACHE_KEY_RANKING_VERSION, 1)
    except Exception:
        ranking_version = 1
    cache_key = f"{CACHE_KEY_CATEGORIZED_MOVIES}_{ranking_version}_{city_key}_{lang_key}"

    if not bypass_cache:
        try:
            cached = cache.get(cache_key)
            if cached:
                return cached
        except Exception:
            pass

    city_name = city or 'Bengaluru'
    active_venue_names = list(CinemaVenue.objects.filter(active=True, status='ACTIVE').values_list('name', flat=True))
    require_partner_venue = CinemaVenue.objects.exists()
    valid_showtime = Q(
        theaters__active=True,
        theaters__admin_verified=True,
        theaters__time__gte=now_dt,
        theaters__operational_status__in=('SCHEDULED', 'BOOKING_OPEN'),
        theaters__screen__active=True,
        theaters__screen__operational_status='ACTIVE',
    )
    if require_partner_venue:
        valid_showtime &= Q(theaters__name__in=active_venue_names)

    # Base Query: Curated active catalog excluding OTT-only titles
    movies_qs = (
        Movie.objects.filter(
            is_in_active_catalog=True,
            is_ott_only=False,
            status__in=('CURRENT', 'ADVANCE_BOOKING', 'UPCOMING'),
        )
        .prefetch_related('genres', 'languages', 'posters', 'cast_members')
        .annotate(
            active_shows=Count(
                'theaters',
                filter=valid_showtime,
                distinct=True,
            ),
            city_active_shows=Count(
                'theaters',
                filter=valid_showtime & Q(theaters__city__iexact=city_name),
                distinct=True,
            ),
            bks_count=Count(
                'booking',
                filter=Q(booking__status='CONFIRMED', booking__booked_at__gte=now_dt - datetime.timedelta(days=7)),
                distinct=True,
            ),
        )
    )

    if language_code:
        l_code = language_code.strip().lower()
        lang_qs = movies_qs.filter(
            Q(original_language__iexact=l_code) | Q(languages__code__iexact=l_code)
        ).distinct()
        if lang_qs.exists():
            movies_qs = lang_qs

    scored_movies = []
    for m in movies_qs:
        active_count = m.active_shows
        city_show_count = m.city_active_shows
        # TMDB's regional discovery feed determines global theatrical status.
        # Local showtimes only determine whether this city can sell tickets.
        bks_count = m.bks_count
        score = calculate_movie_demand_score(m, active_shows_count=active_count, bookings_count=bks_count, today=today)
        is_franchise = bool(FRANCHISE_PATTERN.search(f"{m.title or ''} {m.name or ''}"))
        is_bookable = city_show_count > 0
        is_upcoming = bool(m.release_date and m.release_date > today)
        has_official_advance_booking = is_upcoming and m.is_advance_booking_open and is_bookable
        badge = get_movie_demand_badge(m, is_franchise=is_franchise, is_bookable=is_bookable, today=today)

        # Set runtime attributes for easy template rendering
        m.calculated_demand_score = score
        m.is_franchise_title = is_franchise
        m.is_booking_available = is_bookable
        m.demand_badge = badge
        m.active_shows_count = active_count
        m.has_official_advance_booking = has_official_advance_booking

        if is_bookable:
            m.action_label = 'BOOK NOW'
            m.action_url = reverse('theater_list', kwargs={'movie_id': m.id})
            m.action_css_class = 'btn-card-action book-now'
        elif m.release_date and m.release_date > today:
            m.action_label = 'COMING SOON'
            m.action_url = reverse('movie_detail', kwargs={'movie_id': m.id})
            m.action_css_class = 'btn-card-action coming-soon'
        else:
            m.action_label = 'VIEW DETAILS'
            m.action_url = reverse('movie_detail', kwargs={'movie_id': m.id})
            m.action_css_class = 'btn-card-action coming-soon'

        scored_movies.append(m)

    # Release date is the primary grouping. Promo completeness, then demand, breaks ties.
    sort_movies_by_release_and_promotion(scored_movies)

    # =========================================================
    # A. TRENDING THEATRICAL MOVIES
    # Current theatrical discovery is independent of local showtime coverage.
    # =========================================================
    recent_release_cutoff = today - datetime.timedelta(days=14)
    current_run_cutoff = today - datetime.timedelta(days=28)
    trending_candidates = []
    for movie in scored_movies:
        if not movie.release_date:
            continue
        if movie.status != 'CURRENT':
            continue
        if movie.release_date > today:
            continue
        elif movie.release_date >= recent_release_cutoff and movie.status == 'CURRENT':
            group = 2
        elif movie.release_date >= current_run_cutoff and movie.status == 'CURRENT':
            group = 3
        else:
            continue
        movie.trending_priority = group
        trending_candidates.append(movie)

    trending_candidates.sort(key=lambda movie: (
        movie.trending_priority,
        -movie.calculated_demand_score,
        -float(movie.popularity or 0),
        movie.release_date if movie.trending_priority in (0, 1) else -movie.release_date.toordinal(),
        get_promotional_priority(movie),
        (movie.title or movie.name or '').casefold(),
    ))
    trending_booking_open = trending_candidates[:12]

    trending_ids = {m.id for m in trending_booking_open}

    # =========================================================
    # B. UPCOMING ANTICIPATED MOVIES
    # Major upcoming theatrical releases (release_date > today or UPCOMING status)
    # Sorted by anticipation score. Shows COMING SOON (or ADVANCE OPEN if showtimes exist)
    # =========================================================
    upcoming_anticipated = [
        m for m in scored_movies
        if m.release_date and m.release_date > today and m.status in ('UPCOMING', 'ADVANCE_BOOKING')
    ]
    # Filter to avoid duplicates if an upcoming movie is already in Section A as Advance Open.
    upcoming_anticipated = [m for m in upcoming_anticipated if m.id not in trending_ids]
    if len(upcoming_anticipated) < 4:
        upcoming_anticipated = [
            m for m in scored_movies
            if m.release_date and m.release_date > today and m.status in ('UPCOMING', 'ADVANCE_BOOKING')
        ]

    upcoming_ids = {m.id for m in upcoming_anticipated}

    # =========================================================
    # C. NOW SHOWING
    # Remaining current theatrical movies, whether or not this city has a showtime.
    # =========================================================
    all_now_showing = [
        m for m in scored_movies
        if m.status == 'CURRENT' and m.release_date and m.release_date <= today
        and m.id not in trending_ids and m.id not in upcoming_ids
    ]
    sort_movies_by_release_and_promotion(all_now_showing, newest_date_first=True)
    now_showing = all_now_showing[:12]

    now_showing_ids = {m.id for m in now_showing}

    # =========================================================
    # D. DISCOVER MORE MOVIES (Requirement 2)
    # Additional eligible theatrical releases not displayed in Sections A, B, or C.
    # Excludes OTT-only and expired titles; includes titles with verified posters and release info.
    # =========================================================
    featured_ids = trending_ids | upcoming_ids | now_showing_ids
    discover_more = [
        m for m in all_now_showing
        if m.id not in featured_ids and not m.is_ott_only
    ]
    sort_movies_by_release_and_promotion(discover_more)

    result = {
        'trending_booking_open': trending_booking_open,
        'upcoming_anticipated': upcoming_anticipated,
        'discover_more': discover_more,
        'now_showing': now_showing,
        'total_trending_open': len(trending_booking_open),
        'total_upcoming': len(upcoming_anticipated),
        'total_now_showing': len(now_showing),
        'updated_at': now_dt.strftime('%b %d, %Y at %I:%M %p'),
    }

    try:
        cache.set(cache_key, result, timeout=CACHE_TTL)
    except Exception:
        pass

    return result


def invalidate_movie_ranking_cache():
    """Invalidates cached movie discovery rankings when showtimes or bookings change."""
    try:
        try:
            cache.incr(CACHE_KEY_RANKING_VERSION)
        except (ValueError, NotImplementedError):
            cache.set(CACHE_KEY_RANKING_VERSION, 2, timeout=None)
        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern(f"{CACHE_KEY_CATEGORIZED_MOVIES}_*")
        else:
            for lang in ['all', 'kn', 'ta', 'te', 'ml', 'hi', 'en']:
                cache.delete(f"{CACHE_KEY_CATEGORIZED_MOVIES}_all_{lang}")
                cache.delete(f"{CACHE_KEY_CATEGORIZED_MOVIES}_bengaluru_{lang}")
    except Exception as exc:
        logger.debug(f"Cache invalidation note: {exc}")
