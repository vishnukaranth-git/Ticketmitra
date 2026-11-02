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
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from movies.models import Movie, Theater

logger = logging.getLogger(__name__)

CACHE_KEY_CATEGORIZED_MOVIES = 'ticketmitra_categorized_movies'
CACHE_TTL = 300  # 5 minutes cache for fast discovery

# Regex to detect sequel numbers, chapter indicators, and major Indian/global franchise keywords
FRANCHISE_PATTERN = re.compile(
    r'\b('
    r'2|3|4|5|part\s*\d+|chapter\s*\d+|volume\s*\d+|vol\s*\d+|'
    r'conclusion|returns|reloaded|revolution|legacy|reborn|'
    r'ramayana|jailer|kalki|singham|pushpa|war|tiger|pathaan|'
    r'brahmastra|bramhastra|devara|salaar|baahubali|kgf|vikram|'
    r'spider|avengers|batman|deadpool|wolverine|drishyam|leo|kantara'
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

    # 3. Advance Booking Open Status (+35 pts)
    if movie.is_advance_booking_open or movie.status == 'ADVANCE_BOOKING':
        score += 35.0

    # 4. Active Showtimes Density across cinema screens (up to 35 pts)
    # The more screens screening this title, the higher the exhibitor and audience demand
    score += min(active_shows_count * 2.5, 35.0)

    # 5. Real Audience Ticket Sales & Booking Velocity (up to 35 pts)
    score += min(bookings_count * 5.0, 35.0)

    # 6. Audience Rating & Critique Quality (up to 25 pts)
    rating_val = float(movie.tmdb_rating or movie.rating or 6.5)
    score += rating_val * 2.5

    # 7. Recency bonus for releases within the last 14 days (+15 pts)
    if movie.release_date and (today - datetime.timedelta(days=14)) <= movie.release_date <= today:
        score += 15.0

    return round(score, 1)


def get_movie_demand_badge(movie, is_franchise=False, is_bookable=False):
    """
    Returns an appropriate UI badge label for trending and anticipated movies.
    """
    if movie.is_advance_booking_open or (movie.release_date and movie.release_date > timezone.now().date() and is_bookable):
        return 'ADVANCE OPEN'
    if is_franchise:
        return 'FRANCHISE'
    pop = float(movie.popularity or 0.0)
    if pop >= 150.0:
        return 'TRENDING'
    if pop >= 80.0:
        return 'HIGH DEMAND'
    if movie.release_date and (timezone.now().date() - datetime.timedelta(days=7)) <= movie.release_date <= timezone.now().date():
        return 'NEW RELEASE'
    return None


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
    cache_key = f"{CACHE_KEY_CATEGORIZED_MOVIES}_{city_key}_{lang_key}"

    if not bypass_cache:
        try:
            cached = cache.get(cache_key)
            if cached:
                return cached
        except Exception:
            pass

    city_name = city or 'Bengaluru'

    # Base Query: Curated active catalog excluding OTT-only titles
    movies_qs = (
        Movie.objects.filter(is_in_active_catalog=True, is_ott_only=False)
        .prefetch_related('genres', 'languages')
        .annotate(
            active_shows=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__time__gte=now_dt)
            ),
            city_active_shows=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__city__iexact=city_name, theaters__time__gte=now_dt)
            ),
            bks_count=Count('booking'),
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
        bks_count = m.bks_count
        score = calculate_movie_demand_score(m, active_shows_count=active_count, bookings_count=bks_count, today=today)
        is_franchise = bool(FRANCHISE_PATTERN.search(f"{m.title or ''} {m.name or ''}"))
        is_bookable = (active_count > 0)
        badge = get_movie_demand_badge(m, is_franchise=is_franchise, is_bookable=is_bookable)

        # Set runtime attributes for easy template rendering
        m.calculated_demand_score = score
        m.is_franchise_title = is_franchise
        m.is_booking_available = is_bookable
        m.demand_badge = badge
        m.active_shows_count = active_count

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

    # Sort descending by calculated demand score
    scored_movies.sort(key=lambda x: getattr(x, 'calculated_demand_score', 0), reverse=True)

    # =========================================================
    # A. TRENDING & BOOKING OPEN
    # Strictly movies with active showtimes currently open for booking
    # Prioritizes highest demand, sequels, and major trending releases
    # =========================================================
    trending_booking_open = [
        m for m in scored_movies
        if m.is_booking_available
    ][:12]

    trending_ids = {m.id for m in trending_booking_open}

    # =========================================================
    # B. UPCOMING ANTICIPATED MOVIES
    # Major upcoming theatrical releases (release_date > today or UPCOMING status)
    # Sorted by anticipation score. Shows COMING SOON (or ADVANCE OPEN if showtimes exist)
    # =========================================================
    upcoming_anticipated = [
        m for m in scored_movies
        if (m.release_date and m.release_date > today) or m.status == 'UPCOMING'
    ]
    # Filter to avoid duplicates if an upcoming movie is already in Section A as Advance Open
    upcoming_anticipated = [m for m in upcoming_anticipated if m.id not in trending_ids][:8]
    if len(upcoming_anticipated) < 4:
        upcoming_anticipated = [
            m for m in scored_movies
            if (m.release_date and m.release_date > today) or m.status == 'UPCOMING'
        ][:8]

    upcoming_ids = {m.id for m in upcoming_anticipated}

    # =========================================================
    # C. NOW SHOWING
    # Other running theatrical movies with active showtimes
    # =========================================================
    now_showing = [
        m for m in scored_movies
        if m.is_booking_available and m.id not in trending_ids and m.id not in upcoming_ids
    ]
    if len(now_showing) < 6:
        extra_active = [
            m for m in scored_movies
            if m.is_booking_available and m.id not in [x.id for x in now_showing]
        ][:12]
        now_showing = extra_active

    result = {
        'trending_booking_open': trending_booking_open,
        'upcoming_anticipated': upcoming_anticipated,
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
        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern(f"{CACHE_KEY_CATEGORIZED_MOVIES}_*")
        else:
            for lang in ['all', 'kn', 'ta', 'te', 'ml', 'hi', 'en']:
                cache.delete(f"{CACHE_KEY_CATEGORIZED_MOVIES}_all_{lang}")
                cache.delete(f"{CACHE_KEY_CATEGORIZED_MOVIES}_bengaluru_{lang}")
    except Exception as exc:
        logger.debug(f"Cache invalidation note: {exc}")
