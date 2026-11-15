"""
schedule_service.py -- TicketMitra Intelligent Cinema Schedule Generation Engine
==============================================================================
Ensures every eligible current theatrical movie has valid showtimes in every
participating theatre:
- Normal releases: at least 1 valid showtime per participating theatre.
- Multistarrer releases (is_multistarrer=True): at least 3 valid showtimes per theatre.
- Real database records (Theater + Seat objects).
- Prevents overlapping shows on the same screen (start + runtime + turnaround).
- Preserves existing bookings, reservations, and manual schedules.
- Idempotent and safe for repeated execution.
"""

import datetime
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from movies.models import CinemaVenue, Movie, Screen, Seat, Theater

logger = logging.getLogger(__name__)

# Standard pricing tiers by screen format
SCREEN_FORMAT_PRICES = {
    'IMAX': Decimal('360.00'),
    '4DX': Decimal('420.00'),
    'PXL': Decimal('320.00'),
    'MX4D': Decimal('380.00'),
    'GOLD': Decimal('450.00'),
    'DOLBY 7.1': Decimal('280.00'),
    'STANDARD': Decimal('200.00'),
}

# Standard theatrical daily show slots (Local IST times: 5 flexible non-overlapping daily slots)
STANDARD_SHOW_TIMES = [
    datetime.time(9, 30),   # Morning Show:   09:30 AM
    datetime.time(12, 45),  # Matinee Show:   12:45 PM
    datetime.time(16, 0),   # Afternoon Show: 04:00 PM
    datetime.time(19, 15),  # Evening Show:   07:15 PM
    datetime.time(22, 30),  # Night Show:     10:30 PM
]


def get_eligible_current_movies(today=None):
    """
    Retrieves all verified current theatrical movies eligible for cinema booking:
    - release_date <= today (theatrical release date has arrived)
    - status == 'CURRENT'
    - is_ott_only == False (theatrical run only)
    - released within recent window (last ~60 days)
    Ordered by multistarrer status, popularity, and recency.
    """
    if today is None:
        today = timezone.now().date()

    sixty_days_ago = today - datetime.timedelta(days=60)

    return list(
        Movie.objects.filter(
            status='CURRENT',
            is_ott_only=False,
            release_date__lte=today,
            release_date__gte=sixty_days_ago,
            is_in_active_catalog=True,
        ).order_by('-is_multistarrer', '-popularity', '-release_date')
    )


def is_screen_slot_available(screen, show_dt, runtime_minutes=135, turnaround_minutes=25, exclude_theater_id=None):
    """
    Checks if a screen has an overlapping showtime.
    Interval: [show_dt, show_dt + runtime + turnaround]
    """
    slot_start = show_dt
    slot_end = show_dt + datetime.timedelta(minutes=runtime_minutes + turnaround_minutes)

    # Query all active shows on this screen around this window
    window_start = slot_start - datetime.timedelta(hours=4)
    window_end = slot_end + datetime.timedelta(hours=4)

    existing_shows = Theater.objects.filter(
        screen=screen,
        active=True,
        time__gte=window_start,
        time__lte=window_end,
    ).exclude(operational_status__in=['CANCELLED'])

    if exclude_theater_id:
        existing_shows = existing_shows.exclude(id=exclude_theater_id)

    for ex in existing_shows:
        ex_runtime = ex.movie.runtime if (ex.movie and ex.movie.runtime) else 135
        ex_turnaround = screen.turnaround_minutes if screen.turnaround_minutes else 25
        ex_start = ex.time
        ex_end = ex_start + datetime.timedelta(minutes=ex_runtime + ex_turnaround)

        # Collision check
        if max(slot_start, ex_start) < min(slot_end, ex_end):
            return False

    return True


def ensure_seats_for_theater(theater, screen):
    """
    Ensures seat layout exists for a newly created or existing showtime.
    Generates rows A, B, C, D... with columns 1..N matching screen capacity.
    """
    if Seat.objects.filter(theater=theater).exists():
        return

    cap = screen.capacity if screen and screen.capacity else 40
    cap = max(20, min(cap, 300))

    cols_per_row = 10 if cap >= 40 else 8
    row_count = (cap + cols_per_row - 1) // cols_per_row
    row_letters = [chr(65 + i) for i in range(min(row_count, 26))]

    seats_to_create = []
    created_count = 0

    for r_idx, r_ltr in enumerate(row_letters):
        seat_type = 'VIP' if r_idx >= row_count - 2 and cap >= 40 else 'REGULAR'
        if screen and screen.screen_type in ('GOLD', 'VIP LUXE'):
            seat_type = 'RECLINER'

        for c in range(1, cols_per_row + 1):
            if created_count >= cap:
                break
            seats_to_create.append(
                Seat(
                    theater=theater,
                    screen=screen,
                    seat_number=f"{r_ltr}{c}",
                    row=r_ltr,
                    seat_type=seat_type,
                    is_booked=False,
                    is_blocked=False,
                )
            )
            created_count += 1

    if seats_to_create:
        Seat.objects.bulk_create(seats_to_create, ignore_conflicts=True)


def generate_schedule_for_cinema_network(
    days_ahead=10,
    dry_run=False,
    force_multistarrer_min=3,
    force_standard_min=1,
    target_city='Bengaluru'
):
    """
    Core engine: ensures every eligible current movie has the required minimum showtimes
    in every participating theatre across the cinema network.
    
    Returns a comprehensive execution audit dictionary.
    """
    now = timezone.now()
    today = now.date()

    eligible_movies = get_eligible_current_movies(today=today)
    active_venues = list(
        CinemaVenue.objects.filter(active=True, status='ACTIVE').order_by('name')
    )

    if target_city:
        active_venues = [v for v in active_venues if (v.city or '').lower() == target_city.lower()]

    venues_without_screens = []
    unaccommodated_requests = []
    created_showtimes = []
    existing_preserved = 0

    # Collect available screens per venue
    venue_screens_map = {}
    for venue in active_venues:
        # Match screens by exact or case-insensitive theater_name
        screens = list(Screen.objects.filter(theater_name__iexact=venue.name, active=True).order_by('id'))
        if not screens:
            # Fallback search by containing name
            screens = list(Screen.objects.filter(theater_name__icontains=venue.name.split()[0], active=True).order_by('id'))
        if screens:
            venue_screens_map[venue.name] = screens
        else:
            venues_without_screens.append(venue.name)

    logger.info(
        f"[ScheduleEngine] Starting schedule verification for {len(eligible_movies)} eligible movies "
        f"across {len(active_venues)} active venues ({len(venue_screens_map)} with valid screens)."
    )

    # Days to schedule across (e.g. today, tomorrow, day after)
    schedule_dates = [today + datetime.timedelta(days=d) for d in range(max(1, days_ahead))]

    for movie in eligible_movies:
        min_required = force_multistarrer_min if movie.is_multistarrer else force_standard_min
        runtime = movie.runtime if movie.runtime else 135

        for venue in active_venues:
            v_name = venue.name
            screens = venue_screens_map.get(v_name, [])

            if not screens:
                continue

            # Check existing future showtimes for this movie in this venue
            existing_shows = Theater.objects.filter(
                movie=movie,
                name=v_name,
                active=True,
                time__gte=now,
            ).exclude(operational_status__in=['CANCELLED'])

            current_count = existing_shows.count()
            if current_count >= min_required:
                existing_preserved += current_count
                continue

            # Need to schedule additional shows:
            needed = min_required - current_count
            scheduled_for_this_pair = 0

            for sch_date in schedule_dates:
                if scheduled_for_this_pair >= needed:
                    break

                for show_time in STANDARD_SHOW_TIMES:
                    if scheduled_for_this_pair >= needed:
                        break

                    candidate_dt = timezone.make_aware(
                        datetime.datetime.combine(sch_date, show_time)
                    )
                    # If slot is in the past, skip
                    if candidate_dt <= now + datetime.timedelta(minutes=30):
                        continue

                    # Try to find an available screen for this slot
                    for screen in screens:
                        turnaround = screen.turnaround_minutes if screen.turnaround_minutes else 25
                        if is_screen_slot_available(screen, candidate_dt, runtime, turnaround):
                            # Slot is available!
                            screen_fmt = (screen.screen_type or 'STANDARD').upper()
                            price = SCREEN_FORMAT_PRICES.get(screen_fmt, Decimal('220.00'))

                            if not dry_run:
                                with transaction.atomic():
                                    th = Theater.objects.create(
                                        name=v_name,
                                        movie=movie,
                                        screen=screen,
                                        time=candidate_dt,
                                        location=venue.address or venue.city or 'Bengaluru',
                                        address=venue.address or '',
                                        city=venue.city or 'Bengaluru',
                                        state=venue.state or 'Karnataka',
                                        latitude=venue.latitude,
                                        longitude=venue.longitude,
                                        price=price,
                                        active=True,
                                        operational_status='BOOKING_OPEN',
                                        language=movie.original_language or 'en',
                                    )
                                    ensure_seats_for_theater(th, screen)
                                    created_showtimes.append(th)
                            else:
                                created_showtimes.append({
                                    'venue': v_name,
                                    'movie': movie.get_display_title(),
                                    'screen': screen.name,
                                    'time': candidate_dt,
                                    'price': price,
                                })

                            scheduled_for_this_pair += 1
                            break

            if scheduled_for_this_pair < needed:
                unaccommodated_requests.append({
                    'movie': movie.get_display_title(),
                    'venue': v_name,
                    'needed': needed,
                    'scheduled': scheduled_for_this_pair,
                    'reason': 'All available screens were occupied during valid operational slots.',
                })

    return {
        'success': True,
        'dry_run': dry_run,
        'eligible_movies_count': len(eligible_movies),
        'multistarrer_movies_count': sum(1 for m in eligible_movies if m.is_multistarrer),
        'active_venues_count': len(active_venues),
        'venues_with_screens_count': len(venue_screens_map),
        'venues_without_screens': venues_without_screens,
        'created_showtimes_count': len(created_showtimes),
        'existing_preserved_count': existing_preserved,
        'unaccommodated_count': len(unaccommodated_requests),
        'unaccommodated_details': unaccommodated_requests,
        'timestamp': now.isoformat(),
    }
