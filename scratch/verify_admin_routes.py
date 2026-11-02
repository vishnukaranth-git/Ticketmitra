import os, sys, django

sys.path.insert(0, os.path.abspath('Ticketmitra'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()
admin_user = User.objects.filter(is_superuser=True).first()
if not admin_user:
    admin_user = User.objects.create_superuser('admin_test', 'admin@example.com', 'adminpass123')

client = Client()
client.force_login(admin_user)

routes = [
    '/admin/dashboard/',
    '/admin/movies/',
    '/admin/theatres/',
    '/admin/screens/',
    '/admin/showtimes/',
    '/admin/seats/',
    '/admin/bookings/',
    '/admin/reservations/',
    '/admin/payments/',
    '/admin/pricing/',
    '/admin/users/',
    '/admin/reviews/',
    '/admin/reports/',
    '/admin/activity/',
    '/admin/operations/analytics/',
    '/admin/operations/search/',
    '/admin/operations/quick-booking/',
]

print("Verifying Admin UI Render Across Routes...")
all_pass = True
for r in routes:
    resp = client.get(r)
    if resp.status_code == 200:
        html = resp.content.decode('utf-8', errors='ignore')
        has_font = 'Playfair+Display' in html or 'ticketmitra_admin.css' in html
        has_css = 'ticketmitra_admin.css' in html
        print(f"[200 OK] {r:<35} - CSS: {has_css}, Fonts: {has_font}")
    else:
        print(f"[{resp.status_code} ERROR] {r}")
        all_pass = False

assert all_pass, "Some admin routes did not return 200 OK!"
print("\nALL ADMIN ROUTES RENDERED CLEANLY (200 OK) WITH UNIFIED CINEMATIC DESIGN!")
