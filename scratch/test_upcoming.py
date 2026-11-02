import os
import sys

sys.path.insert(0, './Ticketmitra')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
import django

django.setup()
from movies.services.tmdb_service import TMDBService

tmdb = TMDBService()
res = tmdb.discover_movies({
    'with_origin_country': 'IN',
    'region': 'IN',
    'sort_by': 'primary_release_date.asc',
    'primary_release_date.gte': '2026-11-02',
    'page': 1
})
results = res.get('results', [])[:8]
print(f"Upcoming Indian movies: {len(results)}")
for r in results:
    title = r.get('title') or r.get('name')
    rel = r.get('release_date')
    mid = r.get('id')
    lang = r.get('original_language')
    print(f"   [{mid}] {title} ({lang}) | Rel: {rel} | Pop: {r.get('popularity')}")
