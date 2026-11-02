import os
import sys
import django
import re

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
django.setup()

from django.test import Client

client = Client()
resp = client.get('/')
print(f"HTTP Status: {resp.status_code}")

html = resp.content.decode('utf-8')

# Search for Top Movies This Week titles
ranked_titles = re.findall(r'class="[^"]*ranked-title[^"]*">\s*([^<\n\r]+)', html)
print(f"Top Movies This Week (Hero section): {ranked_titles}")

# Search for Now Showing titles
card_titles = re.findall(r'class="[^"]*card-title-clamped[^"]*">\s*([^<\n\r]+)', html)
print(f"Now Showing / Homepage Cards: {card_titles[:15]}")

# Check if Mandaadi, Animals, etc. appear in the HTML
for name in ['Mandaadi', 'Reporting Live', 'Pradhama Drishtya', 'Epic Classic', 'Animals', 'The Odyssey', 'Hope']:
    found = name.lower() in html.lower()
    print(f"Contains '{name}': {found}")
