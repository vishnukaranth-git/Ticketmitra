import os

views_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'users', 'views.py')
with open(views_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """    # Combine the existing homepage rails without changing their source queries.
    # Keep the first occurrence of each movie and preserve source ordering within
    # stable trailer / no-trailer groups.
    combined_candidates = []
    seen_movie_ids = set()
    released_this_week_ids = {movie.id for movie in released_this_week_movies}
    for movie in released_this_week_movies + now_showing_movies:
        if movie.id not in seen_movie_ids:
            combined_candidates.append(movie)
            seen_movie_ids.add(movie.id)

    movies_with_trailers = []
    movies_without_trailers = []
    for movie in combined_candidates:
        target_group = movies_with_trailers if movie.get_trailer_embed_url() else movies_without_trailers
        target_group.append(movie)
    homepage_movies = movies_with_trailers + movies_without_trailers"""

replacement = """    # Automated Weekly Friday Discovery & Strict Booking Priority:
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

# Check for CRLF
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

# Also add friday_cycle_label to context
ctx_target = "'movies': now_showing_movies[:12],"
ctx_replacement = "'movies': now_showing_movies[:12],\n        'friday_cycle_label': f\"Friday Release Cycle ({cycle_info['current_friday'].strftime('%b %d')} – {cycle_info['cycle_end'].strftime('%b %d, %Y')})\",\n        'is_friday_cycle': cycle_info['is_friday'],"

ctx_target_crlf = ctx_target.replace('\n', '\r\n')
ctx_replacement_crlf = ctx_replacement.replace('\n', '\r\n')

if ctx_target_crlf in content:
    content = content.replace(ctx_target_crlf, ctx_replacement_crlf)
    print("Replaced context target CRLF")
elif ctx_target in content:
    content = content.replace(ctx_target, ctx_replacement)
    print("Replaced context target LF")

with open(views_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Finished updating users/views.py")

