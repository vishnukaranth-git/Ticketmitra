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
from movies.models import Movie

c = Client()
resp = c.get('/')
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

ctx = resp.context
mock_names = {'Mandaadi', 'Reporting Live', 'Pradhama Drishtya Kuttakkar', 'Epic Classic', 'Animals'}

# Check top movies this week
top_titles = [m.name for m in ctx['top_movies_this_week']]
print(f"Top Movies This Week: {top_titles}")
assert not any(name in mock_names for name in top_titles), f"Found mock title in top movies: {top_titles}"

# Check now showing
now_showing_titles = [m.name for m in ctx['now_showing_movies']]
print(f"Now Showing (first 5): {now_showing_titles[:5]}")
assert not any(name in mock_names for name in now_showing_titles), f"Found mock title in now showing: {now_showing_titles}"

# Check Odyssey poster
odyssey = Movie.objects.filter(name__icontains='Odyssey').first()
assert odyssey is not None, "The Odyssey movie not found"
poster = odyssey.get_poster_url()
print(f"The Odyssey poster: {poster}")
assert "9EJDqzAQ0HoNvMDkOQuirXt1RCg" in poster, f"Unexpected Odyssey poster URL: {poster}"
assert "infinity" not in poster.lower() and "endgame" not in poster.lower(), "Avengers poster still linked to Odyssey"

# Check trailer spinner handling in HTML
html = resp.content.decode('utf-8')
assert 'trailerLoadingSpinner' in html, "trailerLoadingSpinner not found in HTML"
assert 'hideTrailerSpinner' in html, "hideTrailerSpinner not found in HTML"
assert 'shown.bs.modal' in html, "shown.bs.modal listener missing"

print("All homepage, trailer, and poster verification checks PASSED!")

