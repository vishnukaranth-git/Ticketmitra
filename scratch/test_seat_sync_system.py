import os
import sys
import json

sys.path.insert(0, os.path.abspath('Ticketmitra'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'Ticketmitra.settings'
import django
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from movies.models import CinemaVenue, Screen, Theater, Seat, Booking, Movie
from movies.admin_views import visual_seat_map_view, seat_action_api

def run_tests():
    print("=" * 70)
    print("TESTING SEAT GENERATION & DATABASE SYNCHRONIZATION SYSTEM")
    print("=" * 70)

    rf = RequestFactory()
    admin_user, _ = User.objects.get_or_create(username='admin_tester', defaults={'is_staff': True, 'is_superuser': True})

    # 1. Setup or retrieve Screen 3
    venue, _ = CinemaVenue.objects.get_or_create(
        name='AMB Kapali cinemas',
        defaults={'city': 'Bengaluru', 'status': 'ACTIVE', 'active': True}
    )
    screen3, _ = Screen.objects.get_or_create(
        theater_name=venue.name,
        name='Screen 3',
        defaults={'screen_type': 'Gold', 'capacity': 30, 'active': True}
    )
    print(f"\n[SETUP] Found/Created Target Screen: {screen3.theater_name} - {screen3.name} (ID: {screen3.id})")

    # Clear any previous seats on screen3 to start from a clean state
    Seat.objects.filter(screen=screen3).delete()
    assert Seat.objects.filter(screen=screen3).count() == 0
    print("[SETUP] Cleared old test seats on Screen 3.")

    # 2. Build 6 rows x 10 seats layout specification (60 seats)
    rows_spec = []
    for i in range(6):
        r_lbl = chr(65 + i) # A to F
        if i < 2:
            s_type = 'REGULAR'
        elif i < 4:
            s_type = 'PREMIUM'
        else:
            s_type = 'RECLINER'
        acc = [1, 10] if i == 0 else []
        rows_spec.append({'row': r_lbl, 'cols': 10, 'seat_type': s_type, 'accessible': acc})

    payload = {
        'action': 'save_screen_layout',
        'screen_id': screen3.id,
        'rows_spec': rows_spec,
        'aisle_columns': [3, 7]
    }

    # 3. First Save: Generate 60 seats on Screen 3
    req = rf.post(
        '/admin/operations/seats/action/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    req.user = admin_user
    res = seat_action_api(req)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = json.loads(res.content)
    print(f"\n--- Test 1: First Layout Save (6 rows x 10 cols) ---")
    print("API Response:", data)
    assert data['success'] is True
    assert data['capacity'] == 60
    assert data['created_count'] == 60
    assert data['total_seats'] == 60

    # Verify actual database records
    db_seats = Seat.objects.filter(screen=screen3, theater__isnull=True)
    count_1 = db_seats.count()
    print(f"[PASS] Persisted {count_1} master seats in DB for Screen 3. Expected: 60.")
    assert count_1 == 60, f"Expected 60, found {count_1}"

    # Verify rows A through F and seat numbers A1-A10, F1-F10
    row_counts = {}
    for s in db_seats:
        row_counts[s.row] = row_counts.get(s.row, 0) + 1
    print("Row breakdown:", sorted(row_counts.items()))
    assert len(row_counts) == 6
    for r in ['A', 'B', 'C', 'D', 'E', 'F']:
        assert row_counts[r] == 10, f"Row {r} has {row_counts[r]} seats, expected 10"

    # Verify seat categories
    a1 = db_seats.get(seat_number='A1')
    assert a1.seat_type == 'ACCESSIBLE', f"A1 should be ACCESSIBLE, got {a1.seat_type}"
    b2 = db_seats.get(seat_number='B2')
    assert b2.seat_type == 'REGULAR', f"B2 should be REGULAR, got {b2.seat_type}"
    c5 = db_seats.get(seat_number='C5')
    assert c5.seat_type == 'PREMIUM', f"C5 should be PREMIUM, got {c5.seat_type}"
    f8 = db_seats.get(seat_number='F8')
    assert f8.seat_type == 'RECLINER', f"F8 should be RECLINER, got {f8.seat_type}"
    print("[PASS] Seat categories and accessible tags persisted accurately.")

    # 4. Test Second Save (Idempotency / No Duplicates)
    print(f"\n--- Test 2: Second Layout Save (Verify No Duplicates) ---")
    req2 = rf.post(
        '/admin/operations/seats/action/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    req2.user = admin_user
    res2 = seat_action_api(req2)
    assert res2.status_code == 200
    data2 = json.loads(res2.content)
    print("API Response on 2nd Save:", data2)
    assert data2['created_count'] == 0, f"Expected 0 new seats created on second save, got {data2['created_count']}"
    assert data2['synced_count'] == 60

    count_2 = Seat.objects.filter(screen=screen3, theater__isnull=True).count()
    print(f"[PASS] Total seats after second save: {count_2} (Strictly 60, zero duplicates).")
    assert count_2 == 60

    # 5. Test visual_seat_map_view Rendering for Screen 3
    print(f"\n--- Test 3: Verify Visual Seat Map View for Screen 3 ---")
    from django.test.utils import setup_test_environment
    from django.test import Client
    setup_test_environment()
    client = Client()
    client.force_login(admin_user)
    view_res = client.get(f'/admin/seats/?screen_id={screen3.id}')
    assert view_res.status_code == 200
    html = view_res.content.decode('utf-8')
    assert 'Total Capacity: <strong class="text-white">60</strong>' in html
    assert 'Available: <strong>60</strong>' in html
    print("[PASS] Visual Seat Map HTML rendered: Total Capacity: 60, Available: 60.")
    if view_res.context:
        ctx = view_res.context
        print(f"Context total_seats: {ctx['total_seats']}")
        print(f"Context available_count: {ctx['available_count']}")
        print(f"Context rows count: {len(ctx['rows'])}")
        assert ctx['total_seats'] == 60, f"Expected total_seats 60, got {ctx['total_seats']}"
        assert ctx['available_count'] == 60, f"Expected available_count 60, got {ctx['available_count']}"
        assert len(ctx['rows']) == 6, f"Expected 6 rows, got {len(ctx['rows'])}"

    # 6. Test Synchronization to Future Showtimes with Protected Bookings
    print(f"\n--- Test 4: Verify Showtimes Sync & Booking Protection ---")
    movie = Movie.objects.first()
    from django.utils import timezone
    future_time = timezone.now() + timezone.timedelta(days=2)
    showtime, _ = Theater.objects.get_or_create(
        name=venue.name,
        screen=screen3,
        movie=movie,
        time=future_time,
        defaults={'price': 200, 'operational_status': 'BOOKING_OPEN', 'active': True}
    )

    # Re-save layout with screen having an active showtime
    req3 = rf.post(
        '/admin/operations/seats/action/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    req3.user = admin_user
    res3 = seat_action_api(req3)
    assert res3.status_code == 200

    st_seats_count = Seat.objects.filter(theater=showtime).count()
    print(f"[PASS] Synchronized {st_seats_count} seats to upcoming showtime #{showtime.id}.")
    assert st_seats_count == 60

    # Book seat D5
    seat_d5 = Seat.objects.get(theater=showtime, seat_number='D5')
    seat_d5.is_booked = True
    seat_d5.save()
    Booking.objects.get_or_create(
        user=admin_user,
        movie=movie,
        theater=showtime,
        seat=seat_d5,
        defaults={'amount': 250, 'status': 'CONFIRMED'}
    )
    print(f"[SETUP] Booked seat D5 on showtime #{showtime.id}.")

    # Modify layout to change Row D to VIP
    modified_rows = list(rows_spec)
    modified_rows[3] = {'row': 'D', 'cols': 10, 'seat_type': 'VIP', 'accessible': []}
    payload_mod = {
        'action': 'save_screen_layout',
        'screen_id': screen3.id,
        'rows_spec': modified_rows,
        'aisle_columns': [3, 7]
    }
    req4 = rf.post(
        '/admin/operations/seats/action/',
        data=json.dumps(payload_mod),
        content_type='application/json'
    )
    req4.user = admin_user
    res4 = seat_action_api(req4)
    assert res4.status_code == 200

    # Verify D5 in showtime is STILL booked and NOT lost
    d5_after = Seat.objects.get(theater=showtime, seat_number='D5')
    assert d5_after.is_booked is True, "Booked seat D5 must remain booked!"
    assert Booking.objects.filter(theater=showtime, seat=d5_after).exists(), "Booking for D5 must remain intact!"
    print("[PASS] Booking protection verified: D5 booking remained completely intact.")

    print("\n" + "=" * 70)
    print("ALL SEAT GENERATION & DATABASE SYNCHRONIZATION TESTS PASSED!")
    print("=" * 70)

if __name__ == '__main__':
    run_tests()
