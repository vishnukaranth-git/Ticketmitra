import os
import sys

sys.path.insert(0, './Ticketmitra')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
import django

django.setup()
from movies.services.tmdb_service import TMDBService

tmdb = TMDBService()
print("TMDB API Key configured:", bool(tmdb.api_key))

# Discover recent Indian releases across languages
languages = ['kn', 'ta', 'te', 'ml', 'hi', 'bn', 'mr', 'pa', 'gu', 'en']
for lang in languages:
    res = tmdb.discover_movies({
        'with_original_language': lang,
        'region': 'IN',
        'sort_by': 'primary_release_date.desc',
        'primary_release_date.lte': '2026-11-01',
        'page': 1
    })
    results = res.get('results', [])[:3]
    print(f"Language: {lang} -> {len(results)} movies found")
    for r in results:
        title = r.get('title') or r.get('name')
        rel = r.get('release_date')
        mid = r.get('id')
        print(f"   [{mid}] {title} | {rel} | pop: {r.get('popularity')}")
