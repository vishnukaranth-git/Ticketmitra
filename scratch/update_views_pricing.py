with open('Ticketmitra/movies/views.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Update imports
import_target = """    Booking,
    CinemaVenue,
    Genre,
    Language,
    Movie,
    Payment,
    Review,
    ReviewReport,
    Seat,
    SeatReservation,
    Theater,"""

import_replacement = """    Booking,
    CinemaVenue,
    CouponDiscount,
    Genre,
    Language,
    Movie,
    Payment,
    PricingPlan,
    Review,
    ReviewReport,
    Seat,
    SeatReservation,
    Theater,"""

if import_target in c:
    c = c.replace(import_target, import_replacement, 1)

# 2. Update _price_for_seat
price_func_target = """def _price_for_seat(showtime, seat):
    \"\"\"Resolve this show's frozen category price, with legacy base-price fallback.\"\"\"
    prices = showtime.ticket_prices or {}
    value = prices.get(seat.seat_type) or prices.get(seat.seat_type.lower()) or showtime.price or PRICE_PER_SEAT
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(str(showtime.price or PRICE_PER_SEAT))"""

price_func_replacement = """def _price_for_seat(showtime, seat):
    \"\"\"Resolve this show's frozen category price, active PricingPlan, or legacy base-price fallback.\"\"\"
    try:
        val = showtime.get_seat_price(seat.seat_type)
        return Decimal(str(val))
    except Exception:
        prices = showtime.ticket_prices or {}
        value = prices.get(seat.seat_type) or prices.get(seat.seat_type.lower()) or showtime.price or PRICE_PER_SEAT
        return Decimal(str(value))"""

if price_func_target in c:
    c = c.replace(price_func_target, price_func_replacement, 1)

# 3. Add apply_coupon view
apply_coupon_func = """
@login_required(login_url='/login/')
def apply_coupon(request, reservation_id):
    \"\"\"Applies a valid promotional coupon code to an active seat reservation.\"\"\"
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    reservation = get_object_or_404(
        SeatReservation.objects.prefetch_related('seats', 'theater'),
        id=reservation_id,
        user=request.user
    )

    if not reservation.is_active():
        return JsonResponse({'success': False, 'error': 'Reservation has expired.'}, status=400)

    coupon_code = ''
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            coupon_code = (data.get('code') or '').strip().upper()
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    else:
        coupon_code = (request.POST.get('code') or '').strip().upper()

    if not coupon_code:
        return JsonResponse({'success': False, 'error': 'Please enter a coupon code.'}, status=400)

    coupon = CouponDiscount.objects.filter(code=coupon_code, active=True).first()
    if not coupon:
        return JsonResponse({'success': False, 'error': f"Invalid or expired coupon code '{coupon_code}'."}, status=400)

    seats = list(reservation.seats.all())
    original_total = _reservation_price(reservation.theater, seats)

    discount, msg = coupon.calculate_discount(original_total)
    if discount <= 0:
        return JsonResponse({'success': False, 'error': msg or 'Coupon not applicable.'}, status=400)

    new_total = max(Decimal('1.00'), original_total - Decimal(str(discount)))
    reservation.coupon_code = coupon.code
    reservation.discount_amount = Decimal(str(discount))
    reservation.total_amount = new_total
    reservation.save(update_fields=['coupon_code', 'discount_amount', 'total_amount'])

    return JsonResponse({
        'success': True,
        'message': f"Coupon '{coupon.code}' applied! Saved ₹{discount}.",
        'coupon_code': coupon.code,
        'discount_amount': float(discount),
        'original_total': float(original_total),
        'new_total': float(new_total),
    })
"""

# Append apply_coupon before confirm_payment or at end
c += apply_coupon_func

with open('Ticketmitra/movies/views.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated movies/views.py successfully")

