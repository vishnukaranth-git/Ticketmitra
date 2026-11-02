import os
import sys

sys.path.insert(0, './Ticketmitra')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
import django

django.setup()
from movies.services.tmdb_service import TMDBService

tmdb = TMDBService()
# Test watch providers for a well-known movie (e.g. 299534 Avengers: Endgame, or Indian title 579974 RRR, or 656908)
for mid in [299534, 579974, 1368337]:
    res = tmdb._request(f'movie/{mid}/watch/providers')
    in_prov = res.get('results', {}).get('IN', {})
    print(f"Movie #{mid}: link={in_prov.get('link')}")
    flat = in_prov.get('flatrate', [])
    print(f"  flatrate providers: {[p.get('provider_name') for p in flat]}")
