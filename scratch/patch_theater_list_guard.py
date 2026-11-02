import os

views_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'movies', 'views.py')
with open(views_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """    if CinemaVenue.objects.exists():
        scheduled_shows = scheduled_shows.filter(name__in=active_venues)
    return render(request, 'movies/theater_list.html', {"""

replacement = """    if CinemaVenue.objects.exists():
        scheduled_shows = scheduled_shows.filter(name__in=active_venues)

    # Requirement 3: Never allow users into the booking flow without valid available showtimes
    if movie_id is not None and movie and not scheduled_shows.exists():
        messages.warning(
            request,
            f"Ticket bookings are not currently open for '{movie.get_display_title()}'. Showtimes will appear here as soon as tickets become available."
        )
        return redirect('movie_detail', movie_id=movie.id)

    return render(request, 'movies/theater_list.html', {"""

target_crlf = target.replace('\n', '\r\n')
replacement_crlf = replacement.replace('\n', '\r\n')

if target_crlf in content:
    content = content.replace(target_crlf, replacement_crlf)
    print("Replaced CRLF block in theater_list")
elif target in content:
    content = content.replace(target, replacement)
    print("Replaced LF block in theater_list")
else:
    print("Target block not found in theater_list")

with open(views_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Finished patching theater_list")

