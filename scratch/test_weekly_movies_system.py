import os
import sys
import datetime
import django

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
django.setup()

from django.test.utils import setup_test_environment
setup_test_environment()
from django.test import Client
from django.utils import timezone
from movies.models import Movie, Theater, Screen
from movies.services.weekly_sync_service import (
    get_current_friday_cycle,
    get_bookable_movies_for_section,
    sync_weekly_movies,
)

print("=" * 70)
print("TESTING AUTOMATIC WEEKLY MOVIE DISCOVERY & BOOKING PRIORITY SYSTEM")
print("=" * 70)

# -------------------------------------------------------------
# Test 1: Friday Release Cycle Calculation
# -------------------------------------------------------------
cycle = get_current_friday_cycle()
print(f"\n[Test 1] Current Friday Cycle: {cycle['current_friday']} to {cycle['cycle_end']}")
assert cycle['current_friday'].weekday() == 4, f"Current Friday is not a Friday! (weekday={cycle['current_friday'].weekday()})"
assert (cycle['cycle_end'] - cycle['current_friday']).days == 6, "Cycle should span 7 days (Friday through Thursday)"
print("[PASS] Friday release cycle calculation verified.")

# -------------------------------------------------------------
# Test 2: Main Movies Section Availability & Booking Priority
# -------------------------------------------------------------
now = timezone.now()
bookable_data = get_bookable_movies_for_section(now_dt=now)
homepage_movies = bookable_data['homepage_movies']
released_this_week_ids = bookable_data['released_this_week_ids']

print(f"\n[Test 2] Total bookable movies in main section: {len(homepage_movies)}")
print(f"New releases this week with active bookings: {len(released_this_week_ids)}")

assert len(homepage_movies) > 0, "No bookable movies returned for main section!"

# Verify that EVERY single movie in homepage_movies has active future showtimes!
for m in homepage_movies:
    active_shows = m.theaters.filter(active=True, time__gte=now).count()
    assert active_shows > 0, f"Movie '{m.name}' has 0 active future showtimes but appeared in homepage_movies!"

print(f"[PASS] All {len(homepage_movies)} movies in main Movies section strictly have active bookable showtimes.")

# Verify booking priority: new releases this week appear first
first_few = homepage_movies[:len(released_this_week_ids)]
for m in first_few:
    assert m.id in released_this_week_ids, f"Movie '{m.name}' not prioritized in new releases group!"

print("[PASS] New releases in Friday cycle are prioritized first at the top of the rail.")

# -------------------------------------------------------------
# Test 3: Auto-removal on Showtime Expiry / Deactivation
# -------------------------------------------------------------
test_movie = homepage_movies[0]
print(f"\n[Test 3] Testing auto-removal for movie #{test_movie.id} ('{test_movie.name}')...")
# Temporarily deactivate its showtimes
shows = list(test_movie.theaters.filter(active=True, time__gte=now))
test_movie.theaters.filter(id__in=[s.id for s in shows]).update(active=False)

# Re-query bookable movies
updated_data = get_bookable_movies_for_section(now_dt=now)
updated_ids = [m.id for m in updated_data['homepage_movies']]

assert test_movie.id not in updated_ids, f"Movie '{test_movie.name}' should have been removed after showtimes deactivated!"
print(f"[PASS] Movie #{test_movie.id} automatically removed when showtimes expired/deactivated.")

# Restore showtimes
Theater.objects.filter(id__in=[s.id for s in shows]).update(active=True)
restored_data = get_bookable_movies_for_section(now_dt=now)
restored_ids = [m.id for m in restored_data['homepage_movies']]
assert test_movie.id in restored_ids, f"Movie '{test_movie.name}' should have returned after showtimes restored!"
print(f"[PASS] Movie #{test_movie.id} automatically re-included when showtimes became available.")

# -------------------------------------------------------------
# Test 4: Frontend Live API Endpoint
# -------------------------------------------------------------
print("\n[Test 4] Testing GET /movies/api/weekly-movies/ API endpoint...")
c = Client()
api_resp = c.get('/movies/api/weekly-movies/')
assert api_resp.status_code == 200, f"Expected 200, got {api_resp.status_code}"
data = api_resp.json()

assert data['success'] is True, "API returned success=False"
assert data['count'] > 0, "API returned count=0"
assert 'html' in data and len(data['html']) > 100, "API did not return pre-rendered card HTML"
assert 'BOOK NOW' in data['html'], "Pre-rendered HTML does not contain 'BOOK NOW' button"
assert 'carousel-card-item' in data['html'], "Missing carousel-card-item in rendered HTML"
assert data['movies'][0]['is_bookable'] is True, "First movie is_bookable should be True"

print(f"[PASS] API endpoint returned {data['count']} bookable movies with live card HTML and cycle: '{data.get('cycle_label')}'")

# -------------------------------------------------------------
# Test 5: Homepage Render & UI Verification
# -------------------------------------------------------------
print("\n[Test 5] Testing Homepage Render...")
home_resp = c.get('/')
assert home_resp.status_code == 200, f"Homepage returned {home_resp.status_code}"
home_html = home_resp.content.decode('utf-8')

assert 'id="moviesSection"' in home_html, "moviesSection missing from homepage"
assert 'id="homepageMoviesRail"' in home_html, "homepageMoviesRail missing from homepage"
assert 'id="refreshWeeklyMoviesBtn"' in home_html, "refreshWeeklyMoviesBtn missing from homepage"
assert 'id="weeklyCycleBadge"' in home_html, "weeklyCycleBadge missing from homepage"
assert 'BOOK NOW' in home_html, "BOOK NOW button missing from homepage"
assert 'NEW THIS WEEK' in home_html, "NEW THIS WEEK badge missing from homepage"

print("[PASS] Homepage rendered with Friday cycle badge, refresh button, and working BOOK NOW buttons.")

# -------------------------------------------------------------
# Test 6: Graceful Error Handling & Data Retention
# -------------------------------------------------------------
print("\n[Test 6] Testing Error Tolerance with Invalid API Key...")
from movies.services.tmdb_service import TMDBService
tmdb_dummy = TMDBService(api_key='invalid_key_for_testing')
res_fallback = tmdb_dummy.search_movies('Test Query')
assert res_fallback == {} or res_fallback.get('results') == [], "Dummy service should gracefully return empty dict"

# Verify database movies were not wiped out
db_movie_count = Movie.objects.filter(is_in_active_catalog=True).count()
assert db_movie_count > 50, f"Database movies unexpectedly dropped ({db_movie_count})!"
print(f"[PASS] Catalog integrity intact ({db_movie_count} active movies preserved).")

print("\n" + "=" * 70)
print("ALL AUTOMATED WEEKLY MOVIES & BOOKING AVAILABILITY TESTS PASSED!")
print("=" * 70)

