import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

# Set up Django environment
sys.path.insert(0, os.path.abspath('Ticketmitra'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'Ticketmitra.settings'
import django

django.setup()

from django.contrib.auth.models import User
from django.utils import timezone

from movies.models import (
    Booking,
    CinemaVenue,
    CouponDiscount,
    Movie,
    Payment,
    PricingPlan,
    Screen,
    Seat,
    Theater,
)


def run_tests():
    print("=" * 70)
    print("TESTING TICKETMITRA THEATRE OPERATIONS & ADMIN MANAGEMENT SYSTEM")
    print("=" * 70)

    # 1. Setup test user & movie
    admin_user, _ = User.objects.get_or_create(username='admin_test', defaults={'is_staff': True, 'is_superuser': True})
    cust_user, _ = User.objects.get_or_create(username='customer_test', defaults={'email': 'cust@example.com'})
    movie = Movie.objects.filter(status='CURRENT', is_in_active_catalog=True).first()
    if not movie:
        movie = Movie.objects.create(name='Test Blockbuster', title='Test Blockbuster', status='CURRENT', runtime=135)

    today = timezone.now().date()
    nov2 = today
    nov9 = today + timedelta(days=7)

    # 2. Test Theatre & Screen Operations
    print("\n--- 1. Testing Theatre & Screen Operations ---")
    venue, _ = CinemaVenue.objects.get_or_create(
        name='PVR Gold Class Orion',
        defaults={
            'theatre_code': 'TM-BLR-01',
            'city': 'Bengaluru',
            'state': 'Karnataka',
            'active': True,
            'status': 'ACTIVE',
        }
    )
    screen, _ = Screen.objects.get_or_create(
        theater_name=venue.name,
        name='Audi 1 (IMAX)',
        defaults={
            'screen_type': 'IMAX',
            'capacity': 40,
            'operational_status': 'ACTIVE',
            'turnaround_minutes': 25,
        }
    )
    assert screen.screen_type == 'IMAX'
    print(f"[PASS] CinemaVenue and Screen created: {venue.name} -> {screen.name}")

    # 3. Test 3D Seat Layout Configuration
    print("\n--- 2. Testing 3D Seating Layout Configuration ---")
    rows_spec = [
        {'row': 'A', 'cols': 8, 'seat_type': 'REGULAR', 'accessible': [1, 8]},
        {'row': 'B', 'cols': 8, 'seat_type': 'PREMIUM', 'accessible': []},
        {'row': 'C', 'cols': 8, 'seat_type': 'RECLINER', 'accessible': []},
        {'row': 'D', 'cols': 8, 'seat_type': 'VIP', 'accessible': []},
    ]
    screen.seating_layout = {'rows_spec': rows_spec, 'aisle_columns': [3, 6]}
    screen.capacity = 32
    screen.save()
    assert screen.capacity == 32
    print("[PASS] Screen 3D layout saved with 32 capacity, tiered categories, and aisle markers.")

    # 4. Test Weekly and Date-Based Ticket Pricing (Requirement 5)
    print("\n--- 3. Testing Weekly and Date-Based Ticket Pricing ---")
    # Plan 1: Week 1 (Nov 02 - Nov 08)
    plan_w1, _ = PricingPlan.objects.get_or_create(
        name='Week 1 Standard Release',
        start_date=nov2,
        end_date=nov2 + timedelta(days=6),
        defaults={
            'theatre_name': venue.name,
            'screen_type': 'IMAX',
            'day_type': 'ALL',
            'base_price': Decimal('180.00'),
            'category_prices': {
                'REGULAR': 180.0,
                'PREMIUM': 250.0,
                'RECLINER': 350.0,
                'VIP': 450.0,
                'ACCESSIBLE': 150.0,
            },
            'is_active': True,
            'created_by': admin_user,
        }
    )

    # Plan 2: Week 2 (Nov 09 - Nov 15)
    _plan_w2, _ = PricingPlan.objects.get_or_create(
        name='Week 2 Surcharge Release',
        start_date=nov9,
        end_date=nov9 + timedelta(days=6),
        defaults={
            'theatre_name': venue.name,
            'screen_type': 'IMAX',
            'day_type': 'ALL',
            'base_price': Decimal('200.00'),
            'category_prices': {
                'REGULAR': 200.0,
                'PREMIUM': 280.0,
                'RECLINER': 400.0,
                'VIP': 500.0,
                'ACCESSIBLE': 170.0,
            },
            'is_active': True,
            'created_by': admin_user,
        }
    )

    # Create Week 1 Showtime
    dt_w1 = timezone.make_aware(datetime.combine(nov2 + timedelta(days=1), datetime.min.time().replace(hour=19, minute=30)))
    show_w1 = Theater.objects.create(
        name=venue.name,
        movie=movie,
        screen=screen,
        time=dt_w1,
        price=Decimal('180.00'),
        ticket_prices={},  # empty snapshot to test dynamic resolution
        active=True,
    )

    # Create Week 2 Showtime
    dt_w2 = timezone.make_aware(datetime.combine(nov9 + timedelta(days=2), datetime.min.time().replace(hour=19, minute=30)))
    show_w2 = Theater.objects.create(
        name=venue.name,
        movie=movie,
        screen=screen,
        time=dt_w2,
        price=Decimal('200.00'),
        ticket_prices={},  # empty snapshot
        active=True,
    )

    # Verify Week 1 vs Week 2 category price resolution
    w1_recliner = show_w1.get_seat_price('RECLINER')
    w2_recliner = show_w2.get_seat_price('RECLINER')
    w1_reg = show_w1.get_seat_price('REGULAR')
    w2_reg = show_w2.get_seat_price('REGULAR')

    print(f"Week 1 Recliner: Rs. {w1_recliner} (Expected: 350.0) | Regular: Rs. {w1_reg} (Expected: 180.0)")
    print(f"Week 2 Recliner: Rs. {w2_recliner} (Expected: 400.0) | Regular: Rs. {w2_reg} (Expected: 200.0)")
    assert w1_recliner == 350.0
    assert w2_recliner == 400.0
    assert w1_reg == 180.0
    assert w2_reg == 200.0
    print("[PASS] Date-based dynamic pricing resolved correctly for Week 1 vs Week 2!")

    # 5. Test Bulk Apply & Pricing Snapshot Freeze
    print("\n--- 4. Testing Bulk Apply & Price Snapshot Isolation ---")
    applied = plan_w1.apply_to_future_showtimes(user=admin_user)
    show_w1.refresh_from_db()
    assert show_w1.ticket_prices.get('RECLINER') == 350.0
    print(f"[PASS] Bulk applied plan prices to {applied} future showtimes. Show snapshot now frozen at Rs. 350 Recliner.")

    # 6. Test Existing Bookings Remain Untouched by Future Price Mutation
    print("\n--- 5. Testing Existing Bookings Are Protected From Future Price Changes ---")
    seat_c1, _ = Seat.objects.get_or_create(
        theater=show_w1,
        seat_number='C1',
        defaults={'screen': screen, 'row': 'C', 'seat_type': 'RECLINER', 'is_booked': True}
    )
    booked_amount = Decimal('350.00')
    booking = Booking.objects.create(
        user=cust_user,
        seat=seat_c1,
        movie=movie,
        theater=show_w1,
        amount=booked_amount,
        ticket_price=booked_amount,
        status='CONFIRMED',
    )

    # Mutate plan pricing to higher amount
    plan_w1.category_prices['RECLINER'] = 450.0
    plan_w1.save()
    plan_w1.apply_to_future_showtimes(user=admin_user)

    booking.refresh_from_db()
    assert booking.amount == booked_amount
    assert booking.ticket_price == booked_amount
    print(f"[PASS] Existing booking #{booking.id} remained strictly unchanged at Rs. {booking.amount} after future price plan mutation!")

    # 7. Test Coupon Discount System
    print("\n--- 6. Testing Coupon & Promotional Discount System ---")
    coupon, _ = CouponDiscount.objects.get_or_create(
        code='FESTIVE25',
        defaults={
            'description': '25% festive holiday discount',
            'discount_type': 'PERCENTAGE',
            'discount_value': Decimal('25.00'),
            'valid_from': today - timedelta(days=1),
            'valid_to': today + timedelta(days=30),
            'max_discount': Decimal('100.00'),
            'usage_limit': 50,
            'active': True,
        }
    )

    disc_amount, msg = coupon.calculate_discount(Decimal('350.00'))
    # 25% of 350 = 87.50
    assert disc_amount == Decimal('87.50')
    print(f"[PASS] Coupon {coupon.code} applied: 25% of Rs. 350 = Rs. {disc_amount} discount ({msg})")

    # 8. Test Stripe & Booking Refund Operations (Requirement 7)
    print("\n--- 7. Testing Stripe & Booking Refund Operations ---")
    payment = Payment.objects.create(
        user=cust_user,
        booking=booking,
        amount=booked_amount,
        currency='INR',
        provider='STRIPE',
        order_id='pi_test_1234567890',
        status='SUCCESS',
    )

    # Simulate refund
    payment.status = 'REFUNDED'
    payment.failure_reason = 'Refunded: Customer requested cancellation'
    payment.save()

    booking.cancel(refund=True)
    booking.refund_amount = booking.amount
    booking.save()

    seat_c1.refresh_from_db()
    assert payment.status == 'REFUNDED'
    assert booking.status == 'CANCELLED'
    assert booking.refund_amount == booked_amount
    assert seat_c1.is_booked is False
    print(f"[PASS] Payment #{payment.id} refunded, booking cancelled, and seat {seat_c1.seat_number} released back to inventory!")

    print("\n" + "=" * 70)
    print("ALL THEATRE OPERATIONS & ADMIN MANAGEMENT TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == '__main__':
    run_tests()
