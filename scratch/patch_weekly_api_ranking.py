import os

views_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'movies', 'views.py')
with open(views_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find def weekly_movies_api
start_marker = "def weekly_movies_api(request):"
start_idx = content.find(start_marker)

end_marker = "@csrf_exempt\ndef trigger_weekly_sync_api(request):"
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    new_func = '''def weekly_movies_api(request):
    """
    API endpoint for automated weekly movie discovery and live frontend updates:
    - Automatically retrieves categorized movies: Trending & Booking Open, Upcoming Anticipated, Now Showing.
    - If ?force_sync=1 or ?refresh=1, executes sync_weekly_movies() in backend.
    - Strictly prioritizes high-demand franchise sequels and popular releases with active bookings.
    - Excludes movies with no active showtimes from booking-open sections.
    - Returns JSON with movie metadata, counts, Friday cycle timestamps, and pre-rendered card HTML
      for smooth DOM replacement without reloading the page.
    """
    from django.template.loader import render_to_string
    from movies.services.ranking_service import get_categorized_movies
    from movies.services.weekly_sync_service import sync_weekly_movies, get_current_friday_cycle

    should_sync = request.GET.get('force_sync') in ('1', 'true', 'yes') or request.GET.get('refresh') in ('1', 'true')
    lang_code = request.GET.get('lang', '').strip().lower()
    city_name = request.GET.get('city', '').strip()

    sync_result = None
    if should_sync:
        try:
            sync_result = sync_weekly_movies(force=True)
        except Exception as exc:
            logger.warning(f"weekly_movies_api sync failed: {exc}")

    try:
        now_dt = timezone.now()
        today = now_dt.date()
        cycle = get_current_friday_cycle(today)

        categorized = get_categorized_movies(
            city=city_name if city_name else None,
            language_code=lang_code if lang_code else None,
            now_dt=now_dt,
            bypass_cache=should_sync,
        )

        trending = categorized['trending_booking_open']
        upcoming = categorized['upcoming_anticipated']
        now_showing = categorized['now_showing']

        # Render HTML for all 3 categories
        trending_html = ''.join([
            render_to_string('movies/partials/categorized_movie_card.html', {'movie': m, 'today': today}, request=request)
            for m in trending
        ])
        upcoming_html = ''.join([
            render_to_string('movies/partials/categorized_movie_card.html', {'movie': m, 'today': today}, request=request)
            for m in upcoming
        ])
        now_showing_html = ''.join([
            render_to_string('movies/partials/categorized_movie_card.html', {'movie': m, 'today': today}, request=request)
            for m in now_showing
        ])

        return JsonResponse({
            'success': True,
            'counts': {
                'trending': len(trending),
                'upcoming': len(upcoming),
                'now_showing': len(now_showing),
            },
            'friday_cycle': cycle['current_friday'].strftime('%b %d, %Y'),
            'cycle_label': f"Friday Release Cycle ({cycle['current_friday'].strftime('%b %d')} – {cycle['cycle_end'].strftime('%b %d, %Y')})",
            'sync_executed': bool(sync_result),
            'sync_message': sync_result.get('message') if sync_result else None,
            'trending_html': trending_html,
            'upcoming_html': upcoming_html,
            'now_showing_html': now_showing_html,
            'html': trending_html,
        })
    except Exception as exc:
        logger.error(f"weekly_movies_api error: {exc}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(exc),
            'counts': {'trending': 0, 'upcoming': 0, 'now_showing': 0},
        }, status=500)


'''
    content = content[:start_idx] + new_func + content[end_idx:]
    with open(views_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated weekly_movies_api successfully.")
else:
    print(f"Could not find markers: start={start_idx}, end={end_idx}")

