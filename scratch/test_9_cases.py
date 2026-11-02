import os
import sys

sys.path.insert(0, r"c:\Users\Vishnu Karanth A\OneDrive\Desktop\Internship\Ticketmitra")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')

import django

django.setup()

from django.utils import timezone

from movies.models import Movie

now = timezone.now()
today = now.date()

print(f"Testing the 9 Release Status Verification Cases at {now} (Today: {today}):\n")

test_cases = [
    ("Case 1: Releasing tomorrow with confirmed advance booking", "Jailer 2", "ADVANCE_BOOKING"),
    ("Case 2: Releasing tomorrow/soon without confirmed advance booking", "Ranabaali", "COMING_SOON"),
    ("Case 3: Released yesterday with valid local showtimes", "Animals", "NOW_SHOWING"),
    ("Case 4: Released 9-10 days ago with valid local showtimes (Recent Theatrical)", "Pradhama Drishtya Kuttakkar", "NOW_SHOWING"),
    ("Case 5: Released 30 days ago that still has local showtimes (Held-over)", "The Odyssey", "NOW_SHOWING"),
    ("Case 6: OTT-only movie with no qualifying theatrical release or local showtimes", "Lust Stories 3", "OTT_ONLY"),
    ("Case 7: Old movie with expired showtimes (Theatrical run ended)", "Spider-Man: Brand New Day", "RELEASE_ENDED"),
    ("Case 8: Movie whose theatrical release date is unknown", "Inception", "UNKNOWN"),
    ("Case 9: Movie with theatrical release date but no local screenings in Bengaluru", "The Paradise", "RELEASE_ENDED"), # in Bengaluru
]

all_passed = True
for label, title, expected_status in test_cases:
    movie = Movie.objects.filter(django.db.models.Q(title__iexact=title) | django.db.models.Q(name__iexact=title)).first()
    if not movie:
        print(f"[FAIL] {label}: Movie '{title}' not found!")
        all_passed = False
        continue

    city = "Bengaluru" if "Bengaluru" in label else None
    actual_status = movie.get_release_status(city=city)
    status_label = movie.release_status_label
    is_recent = movie.is_recent_theatrical_release
    is_bookable = movie.is_bookable

    pass_status = (actual_status == expected_status)
    mark = "PASS" if pass_status else "FAIL"
    if not pass_status:
        all_passed = False

    print(f"[{mark}] {label}")
    print(f"       Movie: '{movie.title}' | Rel Date: {movie.release_date} | OTT: {movie.is_ott_only}")
    print(f"       Status: {actual_status} (Expected: {expected_status}) | Display: '{status_label}'")
    print(f"       Recent 14d: {is_recent} | Bookable: {is_bookable}\n")

if all_passed:
    print("ALL 9 TEST CASES PASSED SUCCESSFULLY!")
else:
    print("SOME TEST CASES FAILED - CHECK DETAILS ABOVE.")
