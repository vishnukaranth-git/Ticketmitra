import os

views_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'users', 'views.py')
with open(views_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """    # Automated Weekly Friday Discovery & Strict Booking Priority:
    # Requirement 5:
    # - The Movies section must strictly prioritize movies that are currently available for booking.
    # - Display movies with active showtimes and a working "BOOK NOW" button first.
    # - Movies without available showtimes must NOT appear in the main Movies section.
    # - Upcoming movies that have not yet opened for booking are excluded from this section.
    # - When all showtimes expire or become unavailable, automatically removed.
    from movies.services.weekly_sync_service import (
        get_bookable_movies_for_section,
        get_current_friday_cycle,
    )
    cycle_info = get_current_friday_cycle(today)
    bookable_data = get_bookable_movies_for_section(
        city=city_name,
        language_code=selected_lang,
        now_dt=now,
    )
    homepage_movies = bookable_data['homepage_movies']
    released_this_week_ids = bookable_data['released_this_week_ids']"""

replacement = """    # Intelligent Demand Ranking & 3-Category Discovery:
    # A. TRENDING & BOOKING OPEN (Most anticipated high-demand releases with active bookings)
    # B. UPCOMING ANTICIPATED MOVIES (Major upcoming theatrical releases, COMING SOON)
    # C. NOW SHOWING (Other running theatrical movies with active showtimes)
    from movies.services.ranking_service import get_categorized_movies
    from movies.services.weekly_sync_service import get_current_friday_cycle

    cycle_info = get_current_friday_cycle(today)
    categorized_data = get_categorized_movies(
        city=city_name,
        language_code=selected_lang,
        now_dt=now,
    )
    trending_booking_open = categorized_data['trending_booking_open']
    upcoming_anticipated = categorized_data['upcoming_anticipated']
    now_showing_movies = categorized_data['now_showing']
    homepage_movies = trending_booking_open
    released_this_week_ids = {m.id for m in trending_booking_open if m.demand_badge in ('NEW RELEASE', 'ADVANCE OPEN')}"""

target_crlf = target.replace('\n', '\r\n')
replacement_crlf = replacement.replace('\n', '\r\n')

if target_crlf in content:
    content = content.replace(target_crlf, replacement_crlf)
    print("Replaced CRLF block in users/views.py")
elif target in content:
    content = content.replace(target, replacement)
    print("Replaced LF block in users/views.py")
else:
    print("Target block not found in users/views.py")

# Add categorized variables to context in home render
ctx_target = "'is_friday_cycle': cycle_info['is_friday'],"
ctx_replacement = """'is_friday_cycle': cycle_info['is_friday'],
        'trending_booking_open': trending_booking_open,
        'upcoming_anticipated': upcoming_anticipated,
        'total_trending_open': categorized_data['total_trending_open'],
        'total_upcoming': categorized_data['total_upcoming'],
        'total_now_showing': categorized_data['total_now_showing'],"""

ctx_target_crlf = ctx_target.replace('\n', '\r\n')
ctx_replacement_crlf = ctx_replacement.replace('\n', '\r\n')

if ctx_target_crlf in content and "'trending_booking_open':" not in content:
    content = content.replace(ctx_target_crlf, ctx_replacement_crlf)
    print("Added context variables CRLF")
elif ctx_target in content and "'trending_booking_open':" not in content:
    content = content.replace(ctx_target, ctx_replacement)
    print("Added context variables LF")

with open(views_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Finished patching users/views.py")

