import os
import sys
import django

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
django.setup()

from django.test.utils import setup_test_environment
setup_test_environment()
from django.test import Client
from django.utils import timezone
from movies.models import Movie, Theater
from movies.services.ranking_service import get_categorized_movies

print("=" * 70)
print("TESTING TRENDING & HIGH-DEMAND MOVIE PRIORITIZATION SYSTEM")
print("=" * 70)

c = Client()
now = timezone.now()

# -------------------------------------------------------------
# Test 1: Category A - Trending & Booking Open
# -------------------------------------------------------------
categorized = get_categorized_movies(now_dt=now, bypass_cache=True)
trending = categorized['trending_booking_open']
upcoming = categorized['upcoming_anticipated']
now_showing = categorized['now_showing']

print(f"\n[Test 1] Category A: {len(trending)} movies in Trending & Booking Open")
assert len(trending) > 0, "No movies in Trending & Booking Open!"

# Verify that EVERY movie in Trending has active future showtimes
for m in trending:
    active_shows = m.theaters.filter(active=True, time__gte=now).count()
    assert active_shows > 0, f"Movie '{m.name}' has 0 active showtimes but appears in Trending & Booking Open!"
    assert m.is_booking_available is True, f"Movie '{m.name}' should have is_booking_available=True"

print("[PASS] All movies in Category A strictly have active future showtimes.")

# Verify major franchises and high-demand titles are prioritized
trending_names = [m.name for m in trending]
print(f"Top 5 Trending Titles: {trending_names[:5]}")
assert any('Jailer' in name or 'Odyssey' in name or 'Hope' in name for name in trending_names[:5]), "Top anticipated franchises not prioritized in top 5!"
print("[PASS] High-demand titles and franchise sequels are prioritized at the top.")

# -------------------------------------------------------------
# Test 2: Category B - Upcoming Anticipated Movies
# -------------------------------------------------------------
print(f"\n[Test 2] Category B: {len(upcoming)} movies in Upcoming Anticipated")
upcoming_names = [m.name for m in upcoming]
print(f"Upcoming Anticipated Titles: {upcoming_names[:5]}")
assert any('Ramayana' in name for name in upcoming_names), "'Ramayana: Rise of a Legend' should be in Upcoming Anticipated!"

for m in upcoming:
    # If it has no showtimes, action must be COMING SOON
    if m.theaters.filter(active=True, time__gte=now).count() == 0:
        assert m.is_booking_available is False, f"Upcoming movie '{m.name}' without showtimes marked as bookable!"
        assert m.action_label == 'COMING SOON', f"Upcoming movie '{m.name}' does not have 'COMING SOON' action label!"

print("[PASS] Major upcoming theatrical productions correctly categorized with COMING SOON status.")

# -------------------------------------------------------------
# Test 3: Category C - Now Showing
# -------------------------------------------------------------
print(f"\n[Test 3] Category C: {len(now_showing)} movies in Now Showing")
assert len(now_showing) > 0, "No movies in Now Showing!"
for m in now_showing:
    active_shows = m.theaters.filter(active=True, time__gte=now).count()
    assert active_shows > 0, f"Now Showing movie '{m.name}' has 0 active showtimes!"

print("[PASS] Category C correctly displays other running theatrical movies with active showtimes.")

# -------------------------------------------------------------
# Test 4: Booking Availability Guard (Prevent unbookable flow)
# -------------------------------------------------------------
ramayana = Movie.objects.filter(name__icontains='Ramayana').first()
assert ramayana is not None, "Ramayana movie not found"
print(f"\n[Test 4] Testing booking access guard on unbookable movie: '{ramayana.name}' (ID: {ramayana.id})...")

resp_guard = c.get(f'/movies/{ramayana.id}/theaters/')
# Should redirect to movie_detail
assert resp_guard.status_code == 302, f"Expected 302 redirect for movie with 0 showtimes, got {resp_guard.status_code}"
assert f'/movies/{ramayana.id}/' in resp_guard.url, f"Redirect target should be movie detail, got {resp_guard.url}"
print("[PASS] Unbookable movie navigation successfully intercepted and redirected to movie detail page.")

# -------------------------------------------------------------
# Test 5: Dynamic Promotion When Advance Booking Opens
# -------------------------------------------------------------
print("\n[Test 5] Testing dynamic promotion when advance booking opens...")
from movies.models import Screen
screen = Screen.objects.filter(active=True).first()
future_show = timezone.now() + timezone.timedelta(days=3)
test_show = Theater.objects.create(
    name=screen.theater_name,
    movie=ramayana,
    screen=screen,
    time=future_show,
    price=250.00,
    active=True,
    operational_status='BOOKING_OPEN',
)

cat_updated = get_categorized_movies(now_dt=timezone.now(), bypass_cache=True)
trending_ids_updated = {m.id for m in cat_updated['trending_booking_open']}
assert ramayana.id in trending_ids_updated, f"Movie '{ramayana.name}' should have automatically promoted to Trending & Booking Open!"
print(f"[PASS] '{ramayana.name}' automatically promoted to Trending & Booking Open as soon as showtimes were scheduled.")

# Clean up test showtime
test_show.delete()

# -------------------------------------------------------------
# Test 6: Homepage Render & 3 Categories Layout
# -------------------------------------------------------------
print("\n[Test 6] Testing Homepage Render...")
home_resp = c.get('/')
assert home_resp.status_code == 200, f"Expected 200, got {home_resp.status_code}"
html = home_resp.content.decode('utf-8')

assert 'id="trendingBookingSection"' in html or 'id="moviesSection"' in html, "Trending & Booking Open section missing!"
assert 'id="trendingBookingRail"' in html, "trendingBookingRail missing!"
assert 'id="upcomingAnticipatedSection"' in html, "upcomingAnticipatedSection missing!"
assert 'id="upcomingAnticipatedRail"' in html, "upcomingAnticipatedRail missing!"
assert 'id="nowShowingSection"' in html, "nowShowingSection missing!"
assert 'id="nowShowingRail"' in html, "nowShowingRail missing!"
assert 'TRENDING &amp; BOOKING OPEN' in html or 'TRENDING & BOOKING OPEN' in html, "TRENDING & BOOKING OPEN tag missing!"
assert 'COMING SOON TO THEATRES' in html, "COMING SOON TO THEATRES tag missing!"
assert 'IN THEATRES NOW' in html, "IN THEATRES NOW tag missing!"
assert 'BOOK NOW' in html, "BOOK NOW button missing!"

print("[PASS] Homepage rendered with all 3 distinct categories, tags, and navigation rails.")

# -------------------------------------------------------------
# Test 7: Live Discovery API Endpoint
# -------------------------------------------------------------
print("\n[Test 7] Testing GET /movies/api/weekly-movies/ Live API...")
api_resp = c.get('/movies/api/weekly-movies/')
assert api_resp.status_code == 200, f"Expected 200, got {api_resp.status_code}"
api_data = api_resp.json()
assert api_data['success'] is True, "API returned success=False"
assert 'trending_html' in api_data, "trending_html missing from API response"
assert 'upcoming_html' in api_data, "upcoming_html missing from API response"
assert 'now_showing_html' in api_data, "now_showing_html missing from API response"
assert api_data['counts']['trending'] > 0, "No trending movies in API counts"
assert api_data['counts']['upcoming'] > 0, "No upcoming movies in API counts"

print(f"[PASS] Live discovery API returned: {api_data['counts']}")

print("\n" + "=" * 70)
print("ALL TRENDING & HIGH-DEMAND PRIORITIZATION TESTS PASSED!")
print("=" * 70)

