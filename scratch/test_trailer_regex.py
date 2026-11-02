import os
import sys
import re

sys.path.insert(0, os.path.abspath('Ticketmitra'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'Ticketmitra.settings'
import django
django.setup()

from movies.models import Movie

pat = re.compile(r'(?:youtube(?:-nocookie)?\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})', re.I)

failures = 0
for m in Movie.objects.all():
    if m.trailer_url:
        m1 = pat.search(m.trailer_url)
        if not m1:
            print(f"FAILED on ID {m.id} {m.name}: {m.trailer_url}")
            failures += 1

print(f"Total failures with new pattern: {failures}")
