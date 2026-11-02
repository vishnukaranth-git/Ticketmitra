import logging

logger = logging.getLogger(__name__)
import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import (
    Coalesce,
    ExtractHour,
    TruncDate,
)
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from movies.models import (
    AdminActivity,
    Booking,
    CinemaVenue,
    CouponDiscount,
    Genre,
    Language,
    Movie,
    Payment,
    PricingHistory,
    PricingPlan,
    Review,
    ReviewReport,
    Screen,
    Seat,
    SeatReservation,
    Theater,
)
from movies.views import cleanup_expired_reservations


def record_admin_activity(request, action, obj, details=None):
    AdminActivity.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk or ''),
        details=details or {},
    )


@staff_member_required(login_url='/admin/login/')
def admin_activity_view(request):
    query = request.GET.get('q', '').strip()
    actions = AdminActivity.objects.select_related('actor').all()
    if query:
        actions = actions.filter(Q(action__icontains=query) | Q(object_type__icontains=query) | Q(object_id__icontains=query) | Q(actor__username__icontains=query))
    page_obj = Paginator(actions, 30).get_page(request.GET.get('page', 1))
    return render(request, 'admin/activity_log.html', {'page_obj': page_obj, 'q': query, 'title': 'Administrative Activity Log'})


@staff_member_required
def dashboard_stats_context():
    """Calculates all dynamic statistics for the TicketMitra Operations Center."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())

    # 1. Top row counts
    total_movies = Movie.objects.count()
    current_movies = Movie.objects.filter(status='CURRENT', release_date__lte=now.date()).count()
    active_showtimes = Theater.objects.filter(active=True, time__gte=now).count()
    total_theaters = Theater.objects.count()
    total_screens = Screen.objects.count()
    total_seats = Seat.objects.count()

    # 2. Second row counts
    today_bookings = Booking.objects.filter(booked_at__gte=today_start).count()
    today_rev = Payment.objects.filter(created_at__gte=today_start, status='SUCCESS').aggregate(Sum('amount'))['amount__sum'] or 0.00
    active_reservations = SeatReservation.objects.filter(status='ACTIVE', expires_at__gt=now).count()
    successful_payments = Payment.objects.filter(status='SUCCESS').count()

    # Monthly additions for trend tags
    movies_this_month = Movie.objects.filter(created_at__gte=month_start).count() if hasattr(Movie, 'created_at') else 0
    bookings_this_week = Booking.objects.filter(booked_at__gte=week_start).count()

    # 3. Live Seat Status
    booked_seat_ids = set(Booking.objects.values_list('seat_id', flat=True)) | set(Seat.objects.filter(is_booked=True).values_list('id', flat=True))
    active_res = SeatReservation.objects.filter(status='ACTIVE', expires_at__gt=now)
    reserved_seat_ids = set(active_res.values_list('seats__id', flat=True)) - booked_seat_ids

    total_seats_all = Seat.objects.count()
    booked_count = len(booked_seat_ids)
    reserved_count = len(reserved_seat_ids)
    blocked_count = Seat.objects.filter(is_blocked=True).count()
    available_count = max(0, total_seats_all - booked_count - reserved_count - blocked_count)

    # 4. Theater Overview Cards
    theaters_qs = Theater.objects.select_related('movie', 'screen').order_by('name', 'time')
    # Group distinct venues
    distinct_venues = {}
    for t in theaters_qs:
        v_name = t.name
        if v_name not in distinct_venues:
            screens_count = Screen.objects.filter(theater_name=v_name).count()
            distinct_venues[v_name] = {
                'id': t.id,
                'name': v_name,
                'location': t.location,
                'city': t.city,
                'screens_count': screens_count if screens_count > 0 else 1,
                'sample_screen_id': t.screen.id if t.screen else None,
                'today_shows': 0,
                'total_seats': 0,
                'booked_seats': 0,
                'reserved_seats': 0,
                'available_seats': 0,
            }
        if t.time.date() == now.date():
            distinct_venues[v_name]['today_shows'] += 1

    # Populate seats per venue
    for v_name, v_data in distinct_venues.items():
        v_seats = Seat.objects.filter(theater__name=v_name)
        total_s = v_seats.count()
        b_seats = v_seats.filter(Q(is_booked=True) | Q(booking__isnull=False)).distinct().count()
        r_seats = v_seats.filter(reservations__status='ACTIVE', reservations__expires_at__gt=now).distinct().count()
        v_data['total_seats'] = total_s
        v_data['booked_seats'] = b_seats
        v_data['reserved_seats'] = r_seats
        v_data['available_seats'] = max(0, total_s - b_seats - r_seats)

    # 5. Recent Activity
    recent_activity = []
    for b in Booking.objects.select_related('user', 'movie', 'theater', 'seat').order_by('-booked_at')[:5]:
        recent_activity.append({
            'type': 'booking',
            'icon': 'fa-ticket-alt',
            'color': '#22C55E',
            'title': f"Booking confirmed for {b.movie.get_display_title()}",
            'desc': f"User: {b.user.username} | Seat {b.seat.seat_number} at {b.theater.name}",
            'time': b.booked_at,
        })
    for p in Payment.objects.select_related('user').order_by('-created_at')[:4]:
        status_color = '#22C55E' if p.status == 'SUCCESS' else ('#EF4444' if p.status == 'FAILED' else '#3B82F6')
        recent_activity.append({
            'type': 'payment',
            'icon': 'fa-credit-card',
            'color': status_color,
            'title': f"Payment {p.status} - ₹{p.amount}",
            'desc': f"{p.provider} | Order: {p.order_id} ({p.user.username})",
            'time': p.created_at,
        })
    for r in Review.objects.select_related('user', 'movie').order_by('-created_at')[:3]:
        recent_activity.append({
            'type': 'review',
            'icon': 'fa-star',
            'color': '#F59E0B',
            'title': f"New review on {r.movie.get_display_title()} ({r.rating}★)",
            'desc': f"By {r.user.username}: \"{r.review_text[:60]}...\"",
            'time': r.created_at,
        })

    recent_activity.sort(key=lambda x: x['time'], reverse=True)
    recent_activity = recent_activity[:8]

    # 6. Dynamic Alerts
    alerts = []
    expiring_soon = SeatReservation.objects.filter(
        status='ACTIVE',
        expires_at__gt=now,
        expires_at__lte=now + timedelta(minutes=2)
    ).count()
    if expiring_soon > 0:
        alerts.append({
            'type': 'warning',
            'icon': 'fa-stopwatch',
            'text': f"{expiring_soon} seat reservation(s) expire within 2 minutes."
        })

    failed_today = Payment.objects.filter(created_at__gte=today_start, status='FAILED').count()
    if failed_today > 0:
        alerts.append({
            'type': 'danger',
            'icon': 'fa-exclamation-circle',
            'text': f"{failed_today} payment(s) failed today. Review transaction logs."
        })

    pending_reports = ReviewReport.objects.count()
    if pending_reports > 0:
        alerts.append({
            'type': 'info',
            'icon': 'fa-flag',
            'text': f"{pending_reports} user review report(s) pending moderator review."
        })

    if today_bookings > 0:
        alerts.append({
            'type': 'success',
            'icon': 'fa-check-circle',
            'text': f"{today_bookings} successful ticket bookings confirmed today."
        })

    return {
        'total_movies': total_movies,
        'current_movies': current_movies,
        'current_movies_count': current_movies,
        'active_showtimes': active_showtimes,
        'active_showtimes_count': active_showtimes,
        'total_theaters': total_theaters,
        'total_screens': total_screens,
        'total_seats': total_seats,
        'today_bookings': today_bookings,
        'today_revenue': today_rev,
        'active_reservations': active_reservations,
        'successful_payments': successful_payments,
        'movies_this_month': movies_this_month,
        'bookings_this_week': bookings_this_week,
        'available_count': available_count,
        'available_seats': available_count,
        'reserved_count': reserved_count,
        'reserved_seats': reserved_count,
        'booked_count': booked_count,
        'booked_seats': booked_count,
        'blocked_count': blocked_count,
        'blocked_seats': blocked_count,
        'venues_list': list(distinct_venues.values()),
        'all_theaters': Theater.objects.select_related('movie', 'screen').order_by('-time')[:20],
        'all_screens': Screen.objects.all().order_by('theater_name', 'name'),
        'recent_activity': recent_activity,
        'admin_alerts': alerts,
    }


@staff_member_required
def theater_detail_view(request, theater_id):
    """Premium theater management view with screen cards and stats."""
    theater = get_object_or_404(Theater.objects.select_related('movie', 'screen'), id=theater_id)
    venue_name = theater.name
    screens = Screen.objects.filter(theater_name=venue_name).prefetch_related('seats')

    now = timezone.now()
    today_shows = Theater.objects.filter(name=venue_name, time__date=now.date()).count()
    today_bookings = Booking.objects.filter(theater__name=venue_name, booked_at__date=now.date()).count()

    total_seats = Seat.objects.filter(theater__name=venue_name).count()
    booked_seats = Seat.objects.filter(theater__name=venue_name, is_booked=True).count()
    reserved_seats = Seat.objects.filter(
        theater__name=venue_name,
        reservations__status='ACTIVE',
        reservations__expires_at__gt=now
    ).distinct().count()
    available_seats = max(0, total_seats - booked_seats - reserved_seats)

    # Detailed data for each screen
    screen_cards = []
    for scr in screens:
        s_seats = scr.seats.all()
        s_total = s_seats.count()
        s_booked = s_seats.filter(Q(is_booked=True) | Q(booking__isnull=False)).distinct().count()
        s_reserved = s_seats.filter(reservations__status='ACTIVE', reservations__expires_at__gt=now).distinct().count()
        s_avail = max(0, s_total - s_booked - s_reserved)
        screen_cards.append({
            'screen': scr,
            'capacity': scr.capacity or s_total,
            'total_seats': s_total,
            'available': s_avail,
            'reserved': s_reserved,
            'booked': s_booked,
        })

    showtimes = Theater.objects.filter(name=venue_name).select_related('movie', 'screen').order_by('time')

    context = {
        'theater': theater,
        'venue_name': venue_name,
        'screens_count': screens.count(),
        'total_seats': total_seats,
        'available_seats': available_seats,
        'reserved_seats': reserved_seats,
        'booked_seats': booked_seats,
        'today_shows': today_shows,
        'today_bookings': today_bookings,
        'screen_cards': screen_cards,
        'showtimes': showtimes,
        'title': f"{venue_name} - Cinema Operations",
    }
    return render(request, 'admin/theater_detail.html', context)


@staff_member_required
def screen_detail_view(request, screen_id):
    """Detailed screen management page."""
    screen = get_object_or_404(Screen, id=screen_id)
    seats = Seat.objects.filter(screen=screen).order_by('seat_number')

    now = timezone.now()
    total = seats.count()
    booked = seats.filter(Q(is_booked=True) | Q(booking__isnull=False)).distinct().count()
    reserved = seats.filter(reservations__status='ACTIVE', reservations__expires_at__gt=now).distinct().count()
    blocked = seats.filter(is_blocked=True).count()
    available = max(0, total - booked - reserved - blocked)

    showtimes = Theater.objects.filter(screen=screen).select_related('movie').order_by('-time')[:10]

    context = {
        'screen': screen,
        'total_seats': total,
        'available': available,
        'reserved': reserved,
        'booked': booked,
        'blocked': blocked,
        'seats': seats,
        'showtimes': showtimes,
        'title': f"{screen.theater_name} — {screen.name} ({screen.screen_type})",
    }
    return render(request, 'admin/screen_detail.html', context)


@staff_member_required
def visual_seat_map_view(request, theater_id=None, screen_id=None):
    """
    Visual seat-map management interface.
    Screen-centric seat configuration: loads persisted screen seat layout directly.
    Displays actual database seats in grid rows A, B, C...
    Colors: Green (Available), Blue (Selected), Orange (Reserved), Red (Booked), Gray (Blocked).
    """
    screen_id = screen_id or request.GET.get('screen_id')
    theater_id = theater_id or request.GET.get('theater_id')

    screen = None
    theater = None

    if screen_id:
        screen = get_object_or_404(Screen, id=screen_id)
        theater = Theater.objects.filter(screen=screen).order_by('-time').first()
    elif theater_id:
        theater = get_object_or_404(Theater.objects.select_related('movie', 'screen'), id=theater_id)
        screen = theater.screen
    else:
        screen = Screen.objects.first()
        if screen:
            theater = Theater.objects.filter(screen=screen).order_by('-time').first()

    if not screen:
        messages.error(request, 'No screens found in the system. Please add an auditorium or screen first.')
        return redirect('/admin/screens/')

    # 1. Fetch screen's persisted master seats
    seats_qs = Seat.objects.filter(screen=screen, theater__isnull=True).order_by('row', 'seat_number')

    # If no master seats exist yet, auto-reconcile from screen.seating_layout or existing showtimes
    if not seats_qs.exists():
        layout_spec = (screen.seating_layout or {}).get('rows_spec', [])
        if layout_spec:
            with transaction.atomic():
                for r_item in layout_spec:
                    r_lbl = r_item.get('row', 'A').strip().upper()
                    c_cnt = int(r_item.get('cols', 8))
                    s_type = r_item.get('seat_type', 'REGULAR')
                    acc_list = r_item.get('accessible', [])
                    for col in range(1, c_cnt + 1):
                        seat_no = f"{r_lbl}{col}"
                        this_type = 'ACCESSIBLE' if col in acc_list else s_type
                        Seat.objects.get_or_create(
                            screen=screen,
                            theater=None,
                            seat_number=seat_no,
                            defaults={
                                'row': r_lbl,
                                'seat_type': this_type,
                                'is_booked': False,
                                'is_blocked': False,
                            }
                        )
            seats_qs = Seat.objects.filter(screen=screen, theater__isnull=True).order_by('row', 'seat_number')
        else:
            # Check if there are showtime-specific seats for this screen to adopt as master template
            showtime_seats = Seat.objects.filter(screen=screen).exclude(theater__isnull=True)
            if showtime_seats.exists():
                with transaction.atomic():
                    seen = set()
                    for st in showtime_seats:
                        if st.seat_number not in seen:
                            seen.add(st.seat_number)
                            Seat.objects.get_or_create(
                                screen=screen,
                                theater=None,
                                seat_number=st.seat_number,
                                defaults={
                                    'row': st.row,
                                    'seat_type': st.seat_type,
                                    'is_booked': False,
                                    'is_blocked': False,
                                }
                            )
                seats_qs = Seat.objects.filter(screen=screen, theater__isnull=True).order_by('row', 'seat_number')

    now = timezone.now()
    reserved_seat_names = set()
    booked_seat_names = set()

    if theater:
        cleanup_expired_reservations(theater)
        active_res = SeatReservation.objects.filter(theater=theater, status='ACTIVE', expires_at__gt=now)
        reserved_seat_names = set(active_res.values_list('seats__seat_number', flat=True))
        booked_seat_names = set(Booking.objects.filter(theater=theater).values_list('seat__seat_number', flat=True))

    rows_dict = {}
    for s in seats_qs:
        row_lbl = (s.row or (s.seat_number[0] if s.seat_number and s.seat_number[0].isalpha() else 'A')).upper()
        if row_lbl not in rows_dict:
            rows_dict[row_lbl] = []

        if s.seat_number in booked_seat_names or s.is_booked:
            st = 'booked'
        elif s.seat_number in reserved_seat_names:
            st = 'reserved'
        elif getattr(s, 'is_blocked', False):
            st = 'blocked'
        else:
            st = 'available'

        rows_dict[row_lbl].append({
            'id': s.id,
            'seat_number': s.seat_number,
            'row': row_lbl,
            'seat_type': s.seat_type,
            'status': st,
            'is_booked': (s.seat_number in booked_seat_names or s.is_booked),
            'is_blocked': getattr(s, 'is_blocked', False),
        })

    def natural_sort_key(seat_item):
        num_part = ''.join(c for c in seat_item['seat_number'] if c.isdigit())
        return int(num_part) if num_part else 0

    sorted_rows = [{'row_label': k, 'seats': sorted(rows_dict[k], key=natural_sort_key)} for k in sorted(rows_dict.keys())]

    all_screens = Screen.objects.all().order_by('theater_name', 'name')

    pricing_snapshot = {
        'REGULAR': 180.0,
        'PREMIUM': 250.0,
        'RECLINER': 350.0,
        'VIP': 450.0,
        'ACCESSIBLE': 150.0,
    }
    if screen:
        plan = PricingPlan.objects.filter(screen_type=screen.screen_type, is_active=True).first()
        if plan and plan.category_prices:
            pricing_snapshot.update(plan.category_prices)

    total_seats_count = seats_qs.count()
    context = {
        'theater': theater,
        'screen': screen,
        'rows': sorted_rows,
        'seats_json': json.dumps(sorted_rows),
        'pricing_json': json.dumps(pricing_snapshot),
        'total_seats': total_seats_count,
        'available_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'available'),
        'reserved_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'reserved'),
        'booked_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'booked'),
        'blocked_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'blocked'),
        'all_screens': all_screens,
        'title': f"Manage Seats — {screen.theater_name} · {screen.name}",
    }
    return render(request, 'admin/visual_seat_map.html', context)


@staff_member_required
def seat_action_api(request):
    """
    Handles admin seat operations directly on screens and showtimes:
    - block: mark seat blocked
    - unblock: mark seat unblocked
    - add_seat: add a single seat
    - add_row: add a row of seats
    - generate_seats: quick generate standard seats
    - save_screen_layout: saves 2D/3D layout and persists actual database seats
    - clear_layout: clears unbooked seats for screen
    - reset_test_seats: resets eligible test seats with no booking history
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("Method not allowed")

    data = {}
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    else:
        data = request.POST

    action = data.get('action')
    screen_id = data.get('screen_id')
    theater_id = data.get('theater_id')

    screen = None
    theater = None
    if screen_id:
        screen = get_object_or_404(Screen, id=screen_id)
        if theater_id:
            theater = Theater.objects.filter(id=theater_id, screen=screen).first()
        if not theater:
            theater = Theater.objects.filter(screen=screen).order_by('-time').first()
    elif theater_id:
        theater = get_object_or_404(Theater, id=theater_id)
        screen = theater.screen

    if action in ['block', 'unblock']:
        seat_ids = data.get('seat_ids') or ([data.get('seat_id')] if data.get('seat_id') else [])
        if not seat_ids:
            return JsonResponse({'success': False, 'error': 'No seat specified.'}, status=400)

        seats = Seat.objects.filter(id__in=seat_ids)
        booked_seats = set(Booking.objects.filter(seat__in=seats).values_list('seat_id', flat=True)) | set(seats.filter(is_booked=True).values_list('id', flat=True))
        target_seats = seats.exclude(id__in=booked_seats)

        if action == 'block' and len(seat_ids) == 1 and not target_seats.exists():
            return JsonResponse({'success': False, 'error': 'Cannot block a seat with an existing confirmed booking.'}, status=400)

        target_seats.update(is_blocked=(action == 'block'))
        if target_seats.exists():
            record_admin_activity(request, f"seats_{'blocked' if action == 'block' else 'unblocked'}", target_seats.first(), {'seat_ids': list(target_seats.values_list('id', flat=True)), 'count': target_seats.count()})
        return JsonResponse({
            'success': True,
            'action': action,
            'updated_count': target_seats.count(),
            'skipped_booked': len(booked_seats),
            'message': f"Successfully {action}ed {target_seats.count()} seat(s)."
        })

    elif action == 'add_seat':
        if not screen:
            return JsonResponse({'success': False, 'error': 'Screen is required to add a seat.'}, status=400)

        row = (data.get('row') or 'A').strip().upper()
        seat_number = (data.get('seat_number') or '').strip().upper()
        seat_type = data.get('seat_type') or 'REGULAR'
        if not seat_number:
            return JsonResponse({'success': False, 'error': 'Seat number is required.'}, status=400)

        with transaction.atomic():
            seat, created = Seat.objects.get_or_create(
                screen=screen,
                theater=theater,
                seat_number=seat_number,
                defaults={
                    'row': row,
                    'seat_type': seat_type,
                    'is_booked': False,
                    'is_blocked': False,
                }
            )
            if not created:
                return JsonResponse({'success': False, 'error': f'Seat {seat_number} already exists on this screen.'}, status=409)

            # Also ensure a master template seat exists
            if theater:
                Seat.objects.get_or_create(
                    screen=screen,
                    theater=None,
                    seat_number=seat_number,
                    defaults={
                        'row': row,
                        'seat_type': seat_type,
                        'is_booked': False,
                        'is_blocked': False,
                    }
                )

            screen.capacity = Seat.objects.filter(screen=screen, theater__isnull=True).count()
            screen.save(update_fields=['capacity'])

        return JsonResponse({
            'success': True,
            'message': f"Seat {seat.seat_number} created successfully on {screen.name}.",
            'seat_id': seat.id,
            'seat_number': seat.seat_number,
        })

    elif action == 'reset_test_seats':
        target_theaters = [theater] if theater else list(Theater.objects.filter(screen=screen))
        count = 0
        with transaction.atomic():
            for th in target_theaters:
                booked_seats = set(Booking.objects.filter(theater=th).values_list('seat_id', flat=True))
                reset_qs = Seat.objects.filter(theater=th).exclude(id__in=booked_seats)
                count += reset_qs.count()
                reset_qs.update(is_booked=False, is_blocked=False)
                SeatReservation.objects.filter(theater=th, status='ACTIVE').update(status='CANCELLED')

        return JsonResponse({
            'success': True,
            'message': f"Reset {count} unbooked seats. Booking history remained strictly protected.",
            'reset_count': count
        })

    elif action == 'add_row':
        if not screen:
            return JsonResponse({'success': False, 'error': 'Screen is required to add row.'}, status=400)

        row = (data.get('row') or 'A').strip().upper()
        num_seats = int(data.get('num_seats') or 8)
        seat_type = data.get('seat_type') or 'REGULAR'

        created_count = 0
        with transaction.atomic():
            for col in range(1, num_seats + 1):
                seat_no = f"{row}{col}"
                _, created = Seat.objects.get_or_create(
                    screen=screen,
                    theater=theater,
                    seat_number=seat_no,
                    defaults={
                        'row': row,
                        'seat_type': seat_type,
                        'is_booked': False,
                        'is_blocked': False,
                    }
                )
                if created:
                    created_count += 1
                if theater:
                    Seat.objects.get_or_create(
                        screen=screen,
                        theater=None,
                        seat_number=seat_no,
                        defaults={
                            'row': row,
                            'seat_type': seat_type,
                            'is_booked': False,
                            'is_blocked': False,
                        }
                    )
            screen.capacity = Seat.objects.filter(screen=screen, theater__isnull=True).count()
            screen.save(update_fields=['capacity'])

        return JsonResponse({'success': True, 'message': f"Added Row {row} with {created_count} available seats on {screen.name}."})

    elif action == 'generate_seats':
        if not screen:
            return JsonResponse({'success': False, 'error': 'Screen is required to generate seats.'}, status=400)

        rows = int(data.get('rows') or 4)
        cols = int(data.get('cols') or 8)
        row_letters = [chr(ord('A') + i) for i in range(min(rows, 12))]

        created_count = 0
        with transaction.atomic():
            for r_idx, r_ltr in enumerate(row_letters):
                s_type = 'REGULAR' if r_idx < 2 else ('PREMIUM' if r_idx < 3 else 'VIP')
                for col in range(1, cols + 1):
                    seat_no = f"{r_ltr}{col}"
                    _, created = Seat.objects.get_or_create(
                        screen=screen,
                        theater=theater,
                        seat_number=seat_no,
                        defaults={
                            'row': r_ltr,
                            'seat_type': s_type,
                            'is_booked': False,
                            'is_blocked': False,
                        }
                    )
                    if created:
                        created_count += 1
                    if theater:
                        Seat.objects.get_or_create(
                            screen=screen,
                            theater=None,
                            seat_number=seat_no,
                            defaults={
                                'row': r_ltr,
                                'seat_type': s_type,
                                'is_booked': False,
                                'is_blocked': False,
                            }
                        )
            screen.capacity = Seat.objects.filter(screen=screen, theater__isnull=True).count()
            screen.save(update_fields=['capacity'])

        return JsonResponse({'success': True, 'message': f"Generated {created_count} new available seats for {screen.name}."})

    elif action == 'remove_seat':
        seat_id = data.get('seat_id')
        seat = get_object_or_404(Seat, id=seat_id)
        if seat.is_booked or Booking.objects.filter(seat=seat).exists():
            return JsonResponse({'success': False, 'error': f"Cannot delete seat {seat.seat_number} with booking history."}, status=400)
        seat_num = seat.seat_number
        seat_screen = seat.screen
        with transaction.atomic():
            seat.delete()
            if seat_screen:
                seat_screen.capacity = Seat.objects.filter(screen=seat_screen, theater__isnull=True).count()
                seat_screen.save(update_fields=['capacity'])
        return JsonResponse({'success': True, 'message': f"Seat {seat_num} removed."})

    elif action == 'edit_seat':
        seat_id = data.get('seat_id')
        seat = get_object_or_404(Seat, id=seat_id)
        seat_type = data.get('seat_type') or seat.seat_type
        seat_number = (data.get('seat_number') or seat.seat_number).strip().upper()
        is_blocked = data.get('is_blocked')
        seat.seat_type = seat_type
        seat.seat_number = seat_number
        if is_blocked is not None:
            seat.is_blocked = (is_blocked in [True, 'true', 'True', 1, '1'])
        seat.save()
        return JsonResponse({'success': True, 'message': f"Seat {seat.seat_number} updated."})

    elif action == 'save_screen_layout':
        if not screen:
            return JsonResponse({'success': False, 'error': 'Screen is required to save layout.'}, status=400)

        rows_spec = data.get('rows_spec') or []
        aisle_columns = data.get('aisle_columns', [3, 7])

        total_capacity = 0
        for r_item in rows_spec:
            total_capacity += int(r_item.get('cols', 8))

        with transaction.atomic():
            # 1. Update Screen layout metadata
            layout_data = {
                'rows_spec': rows_spec,
                'aisle_columns': aisle_columns,
                'updated_at': timezone.now().isoformat(),
            }
            screen.seating_layout = layout_data
            if total_capacity > 0:
                screen.capacity = total_capacity
            screen.save(update_fields=['seating_layout', 'capacity'])

            # 2. Persist Screen Master Seats (theater=None)
            new_seat_numbers = set()
            created_count = 0
            updated_count = 0
            synced_count = 0

            for r_item in rows_spec:
                r_lbl = r_item.get('row', 'A').strip().upper()
                c_cnt = int(r_item.get('cols', 8))
                s_type = r_item.get('seat_type', 'REGULAR')
                acc_list = r_item.get('accessible', [])
                for col in range(1, c_cnt + 1):
                    seat_no = f"{r_lbl}{col}"
                    new_seat_numbers.add(seat_no)
                    this_type = 'ACCESSIBLE' if col in acc_list else s_type

                    seat_obj, was_created = Seat.objects.get_or_create(
                        screen=screen,
                        theater=None,
                        seat_number=seat_no,
                        defaults={
                            'row': r_lbl,
                            'seat_type': this_type,
                            'is_booked': False,
                            'is_blocked': False,
                        }
                    )
                    if was_created:
                        created_count += 1
                    else:
                        dirty = False
                        if seat_obj.seat_type != this_type:
                            seat_obj.seat_type = this_type
                            dirty = True
                        if seat_obj.row != r_lbl:
                            seat_obj.row = r_lbl
                            dirty = True
                        if dirty:
                            seat_obj.save(update_fields=['seat_type', 'row'])
                            updated_count += 1
                        synced_count += 1

            # Remove master seats that no longer exist in the updated layout
            Seat.objects.filter(screen=screen, theater__isnull=True).exclude(seat_number__in=new_seat_numbers).delete()

            # 3. Synchronize to all active / future showtimes for this screen
            future_showtimes = list(Theater.objects.filter(screen=screen, active=True, time__gte=timezone.now()))
            for th in future_showtimes:
                protected_seat_numbers = set(
                    Booking.objects.filter(theater=th).values_list('seat__seat_number', flat=True)
                ) | set(
                    SeatReservation.objects.filter(theater=th, status='ACTIVE', expires_at__gt=timezone.now()).values_list('seats__seat_number', flat=True)
                )

                for r_item in rows_spec:
                    r_lbl = r_item.get('row', 'A').strip().upper()
                    c_cnt = int(r_item.get('cols', 8))
                    s_type = r_item.get('seat_type', 'REGULAR')
                    acc_list = r_item.get('accessible', [])
                    for col in range(1, c_cnt + 1):
                        seat_no = f"{r_lbl}{col}"
                        this_type = 'ACCESSIBLE' if col in acc_list else s_type

                        th_seat, th_created = Seat.objects.get_or_create(
                            screen=screen,
                            theater=th,
                            seat_number=seat_no,
                            defaults={
                                'row': r_lbl,
                                'seat_type': this_type,
                                'is_booked': False,
                                'is_blocked': False,
                            }
                        )
                        if not th_created and seat_no not in protected_seat_numbers:
                            if th_seat.seat_type != this_type or th_seat.row != r_lbl:
                                th_seat.seat_type = this_type
                                th_seat.row = r_lbl
                                th_seat.save(update_fields=['seat_type', 'row'])

                # Remove seats from showtime only if not in new layout AND not booked/reserved
                Seat.objects.filter(screen=screen, theater=th).exclude(seat_number__in=new_seat_numbers).exclude(seat_number__in=protected_seat_numbers).delete()

        record_admin_activity(request, 'screen_layout_saved', screen, {
            'screen': screen.name,
            'capacity': screen.capacity,
            'created': created_count,
            'updated': updated_count,
            'synced': synced_count,
            'future_showtimes_synced': len(future_showtimes),
        })

        total_persisted = Seat.objects.filter(screen=screen, theater__isnull=True).count()
        return JsonResponse({
            'success': True,
            'message': f"Saved 3D seating layout for screen {screen.name} ({screen.capacity} capacity). Created {created_count}, updated {updated_count}, synced {synced_count + created_count} seat(s).",
            'capacity': screen.capacity,
            'created_count': created_count,
            'updated_count': updated_count,
            'synced_count': synced_count + created_count,
            'total_seats': total_persisted,
        })

    elif action == 'clear_layout':
        if not screen:
            return JsonResponse({'success': False, 'error': 'Screen is required to clear layout.'}, status=400)

        with transaction.atomic():
            booked_seat_numbers = set(
                Booking.objects.filter(theater__screen=screen).values_list('seat__seat_number', flat=True)
            )
            deleted, _ = Seat.objects.filter(screen=screen, theater__isnull=True).exclude(seat_number__in=booked_seat_numbers).delete()
            # Also clear unbooked seats from any future showtimes
            Seat.objects.filter(screen=screen, is_booked=False).exclude(seat_number__in=booked_seat_numbers).delete()
            screen.capacity = Seat.objects.filter(screen=screen, theater__isnull=True).count()
            screen.save(update_fields=['capacity'])

        return JsonResponse({'success': True, 'message': f"Cleared {deleted} unbooked seats from {screen.name}."})

    return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)


@staff_member_required
def bulk_add_seats_view(request):
    """
    Bulk adds seats (e.g. Rows A to E, 6 seats per row).
    Uses get_or_create to protect against duplicates.
    """
    if request.method == 'POST':
        screen_id = request.POST.get('screen_id')
        theater_id = request.POST.get('theater_id')
        start_row = (request.POST.get('start_row') or 'A').strip().upper()
        end_row = (request.POST.get('end_row') or 'E').strip().upper()
        seats_per_row = int(request.POST.get('seats_per_row') or 6)
        seat_type = request.POST.get('seat_type') or 'REGULAR'

        screen = get_object_or_404(Screen, id=screen_id) if screen_id else None
        theaters = []
        if theater_id:
            theaters = [get_object_or_404(Theater, id=theater_id)]
            if not screen:
                screen = theaters[0].screen
        elif screen:
            theaters = list(Theater.objects.filter(screen=screen, active=True, time__gte=timezone.now()))

        if not screen and not theaters:
            messages.error(request, "No matching screen found.")
            return redirect('/admin/screens/')

        start_ord = ord(start_row[0]) if start_row else ord('A')
        end_ord = ord(end_row[0]) if end_row else ord('E')
        if start_ord > end_ord:
            start_ord, end_ord = end_ord, start_ord

        created_count = 0
        with transaction.atomic():
            for r_code in range(start_ord, end_ord + 1):
                row_str = chr(r_code)
                for n in range(1, seats_per_row + 1):
                    seat_num = f"{row_str}{n}"
                    # Master screen seat
                    _, created = Seat.objects.get_or_create(
                        screen=screen,
                        theater=None,
                        seat_number=seat_num,
                        defaults={
                            'row': row_str,
                            'seat_type': seat_type,
                            'is_booked': False,
                            'is_blocked': False,
                        }
                    )
                    if created:
                        created_count += 1

                    # Sync to theaters if any
                    for th in theaters:
                        Seat.objects.get_or_create(
                            screen=screen,
                            theater=th,
                            seat_number=seat_num,
                            defaults={
                                'row': row_str,
                                'seat_type': seat_type,
                                'is_booked': False,
                                'is_blocked': False,
                            }
                        )
            if screen:
                screen.capacity = Seat.objects.filter(screen=screen, theater__isnull=True).count()
                screen.save(update_fields=['capacity'])

        messages.success(request, f"Successfully created/verified {created_count} seats on screen {screen.name if screen else ''}.")
        return redirect(f"/admin/seats/?screen_id={screen.id}" if screen else '/admin/seats/')

    screens = Screen.objects.all().order_by('theater_name', 'name')
    return render(request, 'admin/bulk_add_seats.html', {'screens': screens})


def parse_analytics_date_filters(request):
    """
    Parses custom date ranges and presets (today, last_7_days, last_30_days, this_month, this_year, all_time).
    Returns (start_dt, end_dt, preset, start_str, end_str).
    """
    now = timezone.now()
    preset = request.GET.get('preset', '').strip().lower()
    start_str = request.GET.get('start_date', '').strip()
    end_str = request.GET.get('end_date', '').strip()

    start_dt = None
    end_dt = None

    if preset == 'today':
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif preset == 'last_7_days':
        start_dt = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif preset == 'last_30_days':
        start_dt = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif preset == 'this_month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif preset == 'this_year':
        start_dt = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif preset == 'all_time':
        start_dt = None
        end_dt = None
    elif start_str or end_str:
        preset = 'custom'
        if start_str:
            try:
                dt_obj = datetime.strptime(start_str, '%Y-%m-%d')
                start_dt = timezone.make_aware(dt_obj.replace(hour=0, minute=0, second=0)) if timezone.is_naive(dt_obj) else dt_obj
            except ValueError:
                start_dt = None
        if end_str:
            try:
                dt_obj = datetime.strptime(end_str, '%Y-%m-%d')
                end_dt = timezone.make_aware(dt_obj.replace(hour=23, minute=59, second=59)) if timezone.is_naive(dt_obj) else dt_obj
            except ValueError:
                end_dt = None
    else:
        # Default to last 30 days if no filter specified
        preset = 'last_30_days'
        start_dt = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    return start_dt, end_dt, preset, start_str, end_str


def get_comprehensive_analytics_data(start_dt=None, end_dt=None):
    """
    Optimized database aggregations for the business dashboard.
    Performs all calculations at the SQL database layer using Count, Sum, TruncDate, ExtractHour,
    preventing large record loading into Python memory.
    """
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    # 1. Real-time Revenue Insights across Standard Timeframes (Daily, Weekly, Monthly, Yearly)
    rev_daily = Payment.objects.filter(created_at__gte=today_start, status='SUCCESS').aggregate(s=Sum('amount'))['s'] or 0.00
    rev_weekly = Payment.objects.filter(created_at__gte=week_start, status='SUCCESS').aggregate(s=Sum('amount'))['s'] or 0.00
    rev_monthly = Payment.objects.filter(created_at__gte=month_start, status='SUCCESS').aggregate(s=Sum('amount'))['s'] or 0.00
    rev_yearly = Payment.objects.filter(created_at__gte=year_start, status='SUCCESS').aggregate(s=Sum('amount'))['s'] or 0.00

    # Real-time Standard Booking Counts
    bookings_daily = Booking.objects.filter(booked_at__gte=today_start).count()
    bookings_weekly = Booking.objects.filter(booked_at__gte=week_start).count()
    bookings_monthly = Booking.objects.filter(booked_at__gte=month_start).count()
    bookings_yearly = Booking.objects.filter(booked_at__gte=year_start).count()

    # 2. Date-filtered Querysets for Dynamic Insights
    booking_qs = Booking.objects.all()
    payment_qs = Payment.objects.all()
    user_qs = User.objects.all()

    if start_dt:
        booking_qs = booking_qs.filter(booked_at__gte=start_dt)
        payment_qs = payment_qs.filter(created_at__gte=start_dt)
        user_qs = user_qs.filter(date_joined__gte=start_dt)
    if end_dt:
        booking_qs = booking_qs.filter(booked_at__lte=end_dt)
        payment_qs = payment_qs.filter(created_at__lte=end_dt)
        user_qs = user_qs.filter(date_joined__lte=end_dt)

    # Period Revenue & Bookings
    period_revenue = payment_qs.filter(status='SUCCESS').aggregate(s=Sum('amount'))['s'] or 0.00
    total_period_bookings = booking_qs.count()
    confirmed_period_bookings = booking_qs.filter(status='CONFIRMED').count()
    cancelled_period_bookings = booking_qs.filter(status='CANCELLED').count()

    # 3. Cancellation and Refund Statistics
    cancelled_booking_refunds = booking_qs.filter(status='CANCELLED').aggregate(s=Sum('refund_amount'))['s'] or 0.00
    refunded_payments_count = payment_qs.filter(status='REFUNDED').count()
    refunded_payments_amount = payment_qs.filter(status='REFUNDED').aggregate(s=Sum('amount'))['s'] or 0.00
    total_refund_amount = float(cancelled_booking_refunds) + float(refunded_payments_amount)

    success_payments_count = payment_qs.filter(status='SUCCESS').count()
    failed_payments_count = payment_qs.filter(status='FAILED').count()
    pending_payments_count = payment_qs.filter(status__in=['CREATED', 'PENDING']).count()
    cancelled_payments_count = payment_qs.filter(status='CANCELLED').count()

    cancellation_rate = round((cancelled_period_bookings / total_period_bookings * 100), 2) if total_period_bookings > 0 else 0.0

    # 4. Booking Trends over Time (Database-level TruncDate aggregation)
    trend_qs = (
        booking_qs.annotate(period_date=TruncDate('booked_at'))
        .values('period_date')
        .annotate(
            booking_count=Count('id'),
            confirmed_count=Count('id', filter=Q(status='CONFIRMED')),
            cancelled_count=Count('id', filter=Q(status='CANCELLED')),
            period_amount=Coalesce(Sum('amount'), Value(0.00), output_field=DecimalField())
        )
        .order_by('period_date')
    )
    trend_labels = [entry['period_date'].strftime('%Y-%m-%d') if entry['period_date'] else 'N/A' for entry in trend_qs]
    trend_booking_counts = [entry['booking_count'] for entry in trend_qs]
    trend_confirmed_counts = [entry['confirmed_count'] for entry in trend_qs]
    trend_cancelled_counts = [entry['cancelled_count'] for entry in trend_qs]
    trend_revenues = [float(entry['period_amount']) for entry in trend_qs]

    # 5. Occupancy Percentage for Each Theater
    theater_seat_stats = Seat.objects.values('theater_id', 'theater__name', 'theater__city', 'theater__location').annotate(
        total_seats=Count('id'),
        booked_seats=Count('id', filter=Q(is_booked=True) | Q(booking__status='CONFIRMED'))
    )
    theater_booking_stats = booking_qs.values('theater_id').annotate(
        period_bookings=Count('id'),
        period_revenue=Coalesce(Sum('amount'), Value(0.00), output_field=DecimalField())
    )
    tb_map = {item['theater_id']: item for item in theater_booking_stats}

    theaters_list = []
    total_network_seats = 0
    total_network_booked_seats = 0

    for ts in theater_seat_stats:
        t_id = ts['theater_id']
        t_name = ts['theater__name'] or f"Theater #{t_id}"
        t_city = ts['theater__city'] or "Bengaluru"
        t_tot = ts['total_seats'] or 0
        t_b = ts['booked_seats'] or 0
        total_network_seats += t_tot
        total_network_booked_seats += t_b

        occ_pct = round((t_b / t_tot * 100), 1) if t_tot > 0 else 0.0
        b_info = tb_map.get(t_id, {})
        p_b = b_info.get('period_bookings', 0)
        p_r = float(b_info.get('period_revenue', 0.00))

        theaters_list.append({
            'theater_id': t_id,
            'name': t_name,
            'city': t_city,
            'total_seats': t_tot,
            'booked_seats': t_b,
            'occupancy_pct': occ_pct,
            'period_bookings': p_b,
            'period_revenue': p_r,
        })

    # Sort theaters by gross performance
    theaters_list.sort(key=lambda x: (x['period_revenue'], x['occupancy_pct']), reverse=True)
    overall_occupancy_pct = round((total_network_booked_seats / total_network_seats * 100), 1) if total_network_seats > 0 else 0.0

    # Top performing theaters (top 8)
    top_theaters = theaters_list[:8]
    top_theater_labels = [f"{t['name']} ({t['city']})" for t in top_theaters]
    top_theater_occupancy = [t['occupancy_pct'] for t in top_theaters]
    top_theater_bookings = [t['period_bookings'] for t in top_theaters]

    # 6. Most Booked Movies
    top_movies_qs = (
        booking_qs.values(
            'movie_id', 'movie__title', 'movie__name', 'movie__original_language',
            'movie__rating', 'movie__tmdb_rating', 'movie__poster_url'
        )
        .annotate(
            booking_count=Count('id'),
            total_revenue=Coalesce(Sum('amount'), Value(0.00), output_field=DecimalField())
        )
        .order_by('-booking_count')[:10]
    )
    top_movies = []
    top_movie_labels = []
    top_movie_counts = []
    top_movie_revenues = []

    for m in top_movies_qs:
        m_title = m['movie__title'] or m['movie__name'] or f"Movie #{m['movie_id']}"
        m_rev = float(m['total_revenue'])
        b_count = m['booking_count']
        top_movies.append({
            'id': m['movie_id'],
            'title': m_title,
            'language': m['movie__original_language'] or 'All',
            'rating': float(m['movie__tmdb_rating'] or m['movie__rating'] or 0.0),
            'booking_count': b_count,
            'total_revenue': m_rev,
        })
        top_movie_labels.append(m_title[:18])
        top_movie_counts.append(b_count)
        top_movie_revenues.append(m_rev)

    # 7. Peak Booking Hours (24-hour distribution via ExtractHour)
    hourly_distribution = [0] * 24
    hourly_qs = (
        booking_qs.annotate(booking_hour=ExtractHour('booked_at'))
        .values('booking_hour')
        .annotate(count=Count('id'))
        .order_by('booking_hour')
    )
    peak_hour = 0
    max_hour_count = 0
    for h in hourly_qs:
        hr = h['booking_hour']
        if hr is not None and 0 <= hr < 24:
            hourly_distribution[hr] = h['count']
            if h['count'] > max_hour_count:
                max_hour_count = h['count']
                peak_hour = hr

    hourly_labels = [f"{i:02d}:00" for i in range(24)]
    peak_hour_display = f"{peak_hour:02d}:00 - {(peak_hour+1)%24:02d}:00"

    # 8. User Growth Reports (Daily, Weekly, Monthly, Yearly + Trend)
    user_total = User.objects.count()
    user_new_today = User.objects.filter(date_joined__gte=today_start).count()
    user_new_week = User.objects.filter(date_joined__gte=week_start).count()
    user_new_month = User.objects.filter(date_joined__gte=month_start).count()
    user_new_year = User.objects.filter(date_joined__gte=year_start).count()
    user_period_new = user_qs.count()

    user_growth_qs = (
        user_qs.annotate(joined_date=TruncDate('date_joined'))
        .values('joined_date')
        .annotate(new_users=Count('id'))
        .order_by('joined_date')
    )
    user_growth_labels = [ug['joined_date'].strftime('%Y-%m-%d') if ug['joined_date'] else 'N/A' for ug in user_growth_qs]
    user_growth_counts = [ug['new_users'] for ug in user_growth_qs]

    return {
        'now': now,
        'rev_daily': float(rev_daily),
        'rev_weekly': float(rev_weekly),
        'rev_monthly': float(rev_monthly),
        'rev_yearly': float(rev_yearly),
        'bookings_daily': bookings_daily,
        'bookings_weekly': bookings_weekly,
        'bookings_monthly': bookings_monthly,
        'bookings_yearly': bookings_yearly,
        'period_revenue': float(period_revenue),
        'total_period_bookings': total_period_bookings,
        'confirmed_period_bookings': confirmed_period_bookings,
        'cancelled_period_bookings': cancelled_period_bookings,
        'cancellation_rate': cancellation_rate,
        'total_refund_amount': total_refund_amount,
        'refunded_payments_count': refunded_payments_count,
        'refunded_payments_amount': float(refunded_payments_amount),
        'success_payments_count': success_payments_count,
        'failed_payments_count': failed_payments_count,
        'pending_payments_count': pending_payments_count,
        'cancelled_payments_count': cancelled_payments_count,
        'trend_labels': trend_labels,
        'trend_booking_counts': trend_booking_counts,
        'trend_confirmed_counts': trend_confirmed_counts,
        'trend_cancelled_counts': trend_cancelled_counts,
        'trend_revenues': trend_revenues,
        'theaters_list': theaters_list,
        'top_theaters': top_theaters,
        'top_theater_labels': top_theater_labels,
        'top_theater_occupancy': top_theater_occupancy,
        'top_theater_bookings': top_theater_bookings,
        'overall_occupancy_pct': overall_occupancy_pct,
        'total_network_seats': total_network_seats,
        'total_network_booked_seats': total_network_booked_seats,
        'top_movies': top_movies,
        'top_movie_labels': top_movie_labels,
        'top_movie_counts': top_movie_counts,
        'top_movie_revenues': top_movie_revenues,
        'hourly_labels': hourly_labels,
        'hourly_distribution': hourly_distribution,
        'peak_hour_display': peak_hour_display,
        'peak_hour_count': max_hour_count,
        'user_total': user_total,
        'user_new_today': user_new_today,
        'user_new_week': user_new_week,
        'user_new_month': user_new_month,
        'user_new_year': user_new_year,
        'user_period_new': user_period_new,
        'user_growth_labels': user_growth_labels,
        'user_growth_counts': user_growth_counts,
    }


@staff_member_required(login_url='/admin/login/')
def analytics_view(request):
    """
    Comprehensive Cinema Operations Admin Dashboard with Real-Time Business Insights.
    Supports filtering by custom date ranges and visualizes revenue, bookings, occupancy,
    top movies, top theaters, peak hours, cancellations, and user growth.
    """
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Access denied. Admin credentials required.")

    start_dt, end_dt, preset, start_str, end_str = parse_analytics_date_filters(request)
    data = get_comprehensive_analytics_data(start_dt, end_dt)

    # Date range string for UI badge
    if preset == 'all_time':
        date_range_display = "All Time"
    elif preset == 'today':
        date_range_display = "Today"
    elif preset == 'last_7_days':
        date_range_display = "Last 7 Days"
    elif preset == 'last_30_days':
        date_range_display = "Last 30 Days"
    elif preset == 'this_month':
        date_range_display = "This Month"
    elif preset == 'this_year':
        date_range_display = "This Year"
    else:
        s_text = start_str or "Beginning"
        e_text = end_str or "Present"
        date_range_display = f"{s_text} to {e_text}"

    context = {
        **data,
        'preset': preset,
        'start_date': start_str or (start_dt.strftime('%Y-%m-%d') if start_dt else ''),
        'end_date': end_str or (end_dt.strftime('%Y-%m-%d') if end_dt else ''),
        'date_range_display': date_range_display,
        # JSON-serialized data for Chart.js
        'trend_labels_json': json.dumps(data['trend_labels']),
        'trend_booking_counts_json': json.dumps(data['trend_booking_counts']),
        'trend_revenues_json': json.dumps(data['trend_revenues']),
        'top_movie_labels_json': json.dumps(data['top_movie_labels']),
        'top_movie_counts_json': json.dumps(data['top_movie_counts']),
        'top_theater_labels_json': json.dumps(data['top_theater_labels']),
        'top_theater_occupancy_json': json.dumps(data['top_theater_occupancy']),
        'hourly_labels_json': json.dumps(data['hourly_labels']),
        'hourly_distribution_json': json.dumps(data['hourly_distribution']),
        'payment_status_data_json': json.dumps([
            data['success_payments_count'],
            data['failed_payments_count'],
            data['pending_payments_count'],
            data['cancelled_payments_count']
        ]),
        'user_growth_labels_json': json.dumps(data['user_growth_labels']),
        'user_growth_counts_json': json.dumps(data['user_growth_counts']),
        'title': "Executive Admin Dashboard — TicketMitra Operations",
    }
    return render(request, 'admin/analytics.html', context)


@staff_member_required(login_url='/admin/login/')
def export_analytics_csv(request):
    """
    Exports dashboard business reports as standardized CSV files.
    Supports reports: 'comprehensive', 'revenue_trend', 'theaters', 'movies', 'peak_hours', 'cancellations', 'users'.
    """
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Access denied. Admin credentials required.")

    report_type = request.GET.get('report', 'comprehensive').strip().lower()
    start_dt, end_dt, preset, _start_str, _end_str = parse_analytics_date_filters(request)
    data = get_comprehensive_analytics_data(start_dt, end_dt)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    today_stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    filename = f"ticketmitra_{report_type}_{today_stamp}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    if report_type == 'revenue_trend':
        writer.writerow(['Date', 'Total Bookings', 'Confirmed Bookings', 'Cancelled Bookings', 'Revenue (INR)'])
        for i in range(len(data['trend_labels'])):
            writer.writerow([
                data['trend_labels'][i],
                data['trend_booking_counts'][i] if i < len(data['trend_booking_counts']) else 0,
                data['trend_confirmed_counts'][i] if i < len(data['trend_confirmed_counts']) else 0,
                data['trend_cancelled_counts'][i] if i < len(data['trend_cancelled_counts']) else 0,
                f"{data['trend_revenues'][i]:.2f}" if i < len(data['trend_revenues']) else "0.00",
            ])

    elif report_type == 'movies':
        writer.writerow(['Rank', 'Movie Title', 'Language', 'Rating', 'Bookings Count', 'Gross Revenue (INR)'])
        for idx, m in enumerate(data['top_movies'], 1):
            writer.writerow([idx, m['title'], m['language'], m['rating'], m['booking_count'], f"{m['total_revenue']:.2f}"])

    elif report_type == 'theaters':
        writer.writerow(['Rank', 'Theater Name', 'City', 'Total Seats', 'Booked Seats', 'Occupancy (%)', 'Period Bookings', 'Period Revenue (INR)'])
        for idx, t in enumerate(data['theaters_list'], 1):
            writer.writerow([idx, t['name'], t['city'], t['total_seats'], t['booked_seats'], f"{t['occupancy_pct']}%", t['period_bookings'], f"{t['period_revenue']:.2f}"])

    elif report_type == 'peak_hours':
        writer.writerow(['Hour Window', 'Bookings Count', 'Percentage of Total (%)'])
        tot_b = sum(data['hourly_distribution']) or 1
        for hr, count in enumerate(data['hourly_distribution']):
            pct = round((count / tot_b * 100), 2)
            writer.writerow([f"{hr:02d}:00 - {(hr+1)%24:02d}:00", count, f"{pct}%"])

    elif report_type == 'cancellations':
        writer.writerow(['Metric', 'Value', 'Details'])
        writer.writerow(['Total Period Bookings', data['total_period_bookings'], 'All booking records in selected period'])
        writer.writerow(['Confirmed Bookings', data['confirmed_period_bookings'], 'Successfully confirmed active bookings'])
        writer.writerow(['Cancelled Bookings', data['cancelled_period_bookings'], 'Bookings marked cancelled'])
        writer.writerow(['Cancellation Rate', f"{data['cancellation_rate']}%", 'Percentage of total bookings cancelled'])
        writer.writerow(['Total Refund Amount (INR)', f"{data['total_refund_amount']:.2f}", 'Sum of cancelled seat refunds'])
        writer.writerow(['Successful Payments', data['success_payments_count'], 'Transactions verified successfully'])
        writer.writerow(['Failed Payments', data['failed_payments_count'], 'Transactions failed or declined'])
        writer.writerow(['Refunded Payments', data['refunded_payments_count'], 'Payment gateway refunded transactions'])

    elif report_type == 'users':
        writer.writerow(['Date', 'New User Registrations'])
        for i in range(len(data['user_growth_labels'])):
            writer.writerow([data['user_growth_labels'][i], data['user_growth_counts'][i]])

    else:
        # Full Comprehensive Business Report
        writer.writerow(['========================================================'])
        writer.writerow(['TICKETMITRA CINEMA OPERATIONS - COMPREHENSIVE BUSINESS REPORT'])
        writer.writerow(['Generated At', timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')])
        writer.writerow(['Filter Preset', preset])
        writer.writerow(['========================================================'])
        writer.writerow([])

        writer.writerow(['1. EXECUTIVE REVENUE SUMMARY (REAL-TIME AGGREGATIONS)'])
        writer.writerow(['Daily Revenue (Today)', f"INR {data['rev_daily']:.2f}"])
        writer.writerow(['Weekly Revenue (This Week)', f"INR {data['rev_weekly']:.2f}"])
        writer.writerow(['Monthly Revenue (This Month)', f"INR {data['rev_monthly']:.2f}"])
        writer.writerow(['Yearly Revenue (This Year)', f"INR {data['rev_yearly']:.2f}"])
        writer.writerow(['Filtered Period Revenue', f"INR {data['period_revenue']:.2f}"])
        writer.writerow(['Filtered Period Bookings', data['total_period_bookings']])
        writer.writerow(['Network Seat Occupancy', f"{data['overall_occupancy_pct']}%"])
        writer.writerow(['Cancellation Rate', f"{data['cancellation_rate']}%"])
        writer.writerow(['Peak Booking Window', data['peak_hour_display']])
        writer.writerow([])

        writer.writerow(['2. MOST BOOKED MOVIES'])
        writer.writerow(['Rank', 'Movie Title', 'Language', 'Rating', 'Bookings Count', 'Gross Revenue (INR)'])
        for idx, m in enumerate(data['top_movies'], 1):
            writer.writerow([idx, m['title'], m['language'], m['rating'], m['booking_count'], f"{m['total_revenue']:.2f}"])
        writer.writerow([])

        writer.writerow(['3. THEATER OCCUPANCY & PERFORMANCE'])
        writer.writerow(['Rank', 'Theater Name', 'City', 'Total Seats', 'Booked Seats', 'Occupancy (%)', 'Period Bookings', 'Gross Revenue (INR)'])
        for idx, t in enumerate(data['theaters_list'], 1):
            writer.writerow([idx, t['name'], t['city'], t['total_seats'], t['booked_seats'], f"{t['occupancy_pct']}%", t['period_bookings'], f"{t['period_revenue']:.2f}"])
        writer.writerow([])

        writer.writerow(['4. HOURLY BOOKING DISTRIBUTION'])
        writer.writerow(['Hour Window', 'Bookings Count'])
        for hr, count in enumerate(data['hourly_distribution']):
            writer.writerow([f"{hr:02d}:00 - {(hr+1)%24:02d}:00", count])
        writer.writerow([])

        writer.writerow(['5. CANCELLATION & REFUND METRICS'])
        writer.writerow(['Cancelled Bookings', data['cancelled_period_bookings']])
        writer.writerow(['Total Refund Amount (INR)', f"{data['total_refund_amount']:.2f}"])
        writer.writerow(['Refunded Payments Count', data['refunded_payments_count']])
        writer.writerow([])

        writer.writerow(['6. USER GROWTH SUMMARY'])
        writer.writerow(['Total Registered Users', data['user_total']])
        writer.writerow(['New Signups Today', data['user_new_today']])
        writer.writerow(['New Signups This Week', data['user_new_week']])
        writer.writerow(['New Signups This Month', data['user_new_month']])
        writer.writerow(['New Signups This Year', data['user_new_year']])

    return response


@staff_member_required
def global_search_view(request):
    """
    Unified admin search across Movies, Users, Theaters, Screens, Seats, Bookings, Payments, Reservations.
    """
    q = (request.GET.get('q') or '').strip()
    results = {
        'query': q,
        'movies': [],
        'users': [],
        'theaters': [],
        'screens': [],
        'seats': [],
        'bookings': [],
        'payments': [],
        'reservations': [],
    }

    if q:
        results['movies'] = list(Movie.objects.filter(
            Q(name__icontains=q) | Q(title__icontains=q) | Q(cast__icontains=q)
        )[:6])

        results['users'] = list(User.objects.filter(
            Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )[:6])

        results['theaters'] = list(Theater.objects.select_related('movie', 'screen').filter(
            Q(name__icontains=q) | Q(city__icontains=q) | Q(movie__name__icontains=q)
        )[:6])

        results['screens'] = list(Screen.objects.filter(
            Q(theater_name__icontains=q) | Q(name__icontains=q) | Q(screen_type__icontains=q)
        )[:6])

        results['seats'] = list(Seat.objects.select_related('theater').filter(
            Q(seat_number__icontains=q) | Q(theater__name__icontains=q)
        )[:8])

        results['bookings'] = list(Booking.objects.select_related('user', 'movie', 'theater', 'seat').filter(
            Q(id__icontains=q) | Q(user__username__icontains=q) | Q(movie__name__icontains=q) | Q(seat__seat_number__icontains=q)
        )[:6])

        results['payments'] = list(Payment.objects.select_related('user').filter(
            Q(order_id__icontains=q) | Q(payment_id__icontains=q) | Q(transaction_id__icontains=q) | Q(user__username__icontains=q)
        )[:6])

        results['reservations'] = list(SeatReservation.objects.select_related('user', 'theater__movie').filter(
            Q(id__icontains=q) | Q(user__username__icontains=q) | Q(theater__movie__name__icontains=q)
        )[:6])

    total_matches = sum(len(v) for k, v in results.items() if k != 'query')

    context = {
        'q': q,
        'results': results,
        'total_matches': total_matches,
        'title': f"Search Results for '{q}' — TicketMitra Operations",
    }
    return render(request, 'admin/global_search.html', context)


@staff_member_required
def quick_booking_view(request):
    """
    Controlled admin 'BOOK NOW' test flow:
    Select Movie -> Select Theater/Showtime -> Visual Seat Map -> Select seats -> Proceed to normal checkout.
    Adheres strictly to existing reservation logic without bypassing payment or reservation rules.
    """
    movie_id = request.GET.get('movie_id')
    theater_id = request.GET.get('theater_id')

    selected_movie = None
    selected_theater = None
    showtimes = []

    if movie_id:
        selected_movie = get_object_or_404(Movie, id=movie_id)
        showtimes = Theater.objects.filter(movie=selected_movie, active=True).select_related('screen').order_by('time')

    if theater_id:
        selected_theater = get_object_or_404(Theater.objects.select_related('movie', 'screen'), id=theater_id)
        selected_movie = selected_theater.movie

    movies = Movie.objects.all().order_by('-popularity')[:20]

    context = {
        'movies': movies,
        'selected_movie': selected_movie,
        'selected_theater': selected_theater,
        'showtimes': showtimes,
        'title': "Controlled Test Booking — TicketMitra Operations",
    }
    return render(request, 'admin/quick_booking.html', context)


# ==============================================================================
# CINEMA OPERATIONS CORE VIEWS (TICKETMITRA OPERATIONS ADMIN PANEL)
# ==============================================================================

def admin_login_view(request):
    """
    Dedicated Cinema Operations login view.
    Only users with is_staff or is_superuser permission can access the operations panel.
    Non-staff users attempting to log in receive a 403 Forbidden access denied response.
    """
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect('/admin/dashboard/')
        return HttpResponseForbidden("Access Denied: You must be an administrator or cinema operations staff member to access this panel.")

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            is_staff = getattr(user, 'is_staff', False)
            is_superuser = getattr(user, 'is_superuser', False)
            if is_staff or is_superuser:
                auth_login(request, user)
                user_display = (getattr(user, 'get_full_name', lambda: '')() or getattr(user, 'username', 'Staff'))
                messages.success(request, f"Welcome to TicketMitra Operations, {user_display}!")
                next_url = request.GET.get('next') or request.POST.get('next') or '/admin/dashboard/'
                return redirect(next_url)
            else:
                return HttpResponseForbidden("Access Denied: You must be an administrator or cinema operations staff member to access this panel.")
        else:
            messages.error(request, "Invalid administrator credentials. Please check your username and password.")

    return render(request, 'admin/login.html', {
        'title': 'Operations Login',
        'next': request.GET.get('next', '/admin/dashboard/'),
    })


def admin_logout_view(request):
    """Logs out administrator and redirects to admin login."""
    auth_logout(request)
    messages.info(request, "You have been logged out of TicketMitra Operations.")
    return redirect('/admin/login/')


@staff_member_required(login_url='/admin/login/')
def admin_dashboard_view(request):
    """
    Production TicketMitra Operations Center Dashboard.
    Presents real-time metrics computed directly from database records.
    """
    now = timezone.now()
    today = now.date()

    # Dashboard filters apply to operational records while catalog totals remain global.
    date_from = request.GET.get('date_from') or today.isoformat()
    date_to = request.GET.get('date_to') or today.isoformat()
    theatre_id = request.GET.get('theatre', '').strip()
    movie_id = request.GET.get('movie', '').strip()
    status_filter = request.GET.get('status', '').strip()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        if end_date < start_date:
            raise ValueError
    except ValueError:
        start_date = end_date = today
        date_from = date_to = today.isoformat()

    shows = Theater.objects.filter(time__date__gte=start_date, time__date__lte=end_date)
    bookings = Booking.objects.filter(booked_at__date__gte=start_date, booked_at__date__lte=end_date)
    reservations = SeatReservation.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
    payments = Payment.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
    if theatre_id.isdigit():
        shows = shows.filter(id=theatre_id)
        bookings = bookings.filter(theater_id=theatre_id)
        reservations = reservations.filter(theater_id=theatre_id)
        payments = payments.filter(Q(booking__theater_id=theatre_id) | Q(bookings__theater_id=theatre_id)).distinct()
    if movie_id.isdigit():
        shows = shows.filter(movie_id=movie_id)
        bookings = bookings.filter(movie_id=movie_id)
        reservations = reservations.filter(theater__movie_id=movie_id)
        payments = payments.filter(Q(booking__movie_id=movie_id) | Q(bookings__movie_id=movie_id)).distinct()
    if status_filter in dict(Booking.STATUS_CHOICES):
        bookings = bookings.filter(status=status_filter)

    total_movies = Movie.objects.count()
    total_theaters = CinemaVenue.objects.count() or Theater.objects.values('name').distinct().count()
    total_screens = Screen.objects.count()
    total_seats = Seat.objects.count()
    today_showtimes = shows.count()
    today_bookings = bookings.count()
    active_reservations = reservations.filter(status='ACTIVE', expires_at__gt=now).count()
    expired_holds = reservations.filter(status='EXPIRED').count()
    successful_payments = payments.filter(status='SUCCESS').count()
    pending_payments = payments.filter(status__in=['CREATED', 'PENDING']).count()
    failed_payments = payments.filter(status='FAILED').count()
    gross_revenue = payments.filter(status='SUCCESS').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    refunds = bookings.aggregate(total=Sum('refund_amount'))['total'] or Decimal('0.00')
    occupancy_total = Seat.objects.filter(theater__in=shows).count()
    occupancy_booked = Seat.objects.filter(theater__in=shows, is_booked=True).count()
    occupancy = round(occupancy_booked * 100 / occupancy_total, 1) if occupancy_total else 0

    # Live Seat Metrics
    booked_count = Seat.objects.filter(is_booked=True).count()
    active_res = reservations.filter(status='ACTIVE', expires_at__gt=now)
    reserved_seat_ids = set(active_res.values_list('seats__id', flat=True))
    reserved_count = len(reserved_seat_ids)
    blocked_count = Seat.objects.filter(is_blocked=True).count()
    available_count = max(0, total_seats - booked_count - reserved_count - blocked_count)

    # Activity and records
    recent_bookings = bookings.select_related('user', 'movie', 'theater', 'seat').order_by('-booked_at')[:8]
    recent_payments = payments.select_related('user').order_by('-created_at')[:8]
    recent_activity = []
    for entry in AdminActivity.objects.select_related('actor').order_by('-created_at')[:6]:
        recent_activity.append({
            'title': entry.action.replace('_', ' ').title(),
            'desc': f'{entry.object_type} #{entry.object_id} · {entry.actor or "System"}',
            'time': entry.created_at,
            'icon': 'fa-clipboard-list',
            'color': '#F59E0B',
        })
    for booking in recent_bookings[:4]:
        recent_activity.append({
            'title': f'Booking #{booking.id} · {booking.status.title()}',
            'desc': f'{booking.movie.get_display_title()} · {booking.theater.name} · {booking.user.username}',
            'time': booking.booked_at,
            'icon': 'fa-ticket-alt',
            'color': '#22C55E',
        })
    for payment in recent_payments[:4]:
        recent_activity.append({
            'title': f'Payment {payment.status.title()} · ₹{payment.amount}',
            'desc': f'{payment.provider} · {payment.order_id}',
            'time': payment.created_at,
            'icon': 'fa-credit-card',
            'color': '#60A5FA',
        })
    recent_activity.sort(key=lambda item: item['time'], reverse=True)

    # Venues overview
    venues = list(CinemaVenue.objects.filter(active=True))
    venues_data = []
    for v in venues:
        sc_count = Screen.objects.filter(theater_name=v.name).count()
        st_count = Seat.objects.filter(theater__name=v.name).count()
        today_shows = Theater.objects.filter(name=v.name, time__date=today).count()
        venues_data.append({
            'venue': v,
            'screens_count': sc_count,
            'seats_count': st_count,
            'today_shows': today_shows,
        })

    context = {
        'total_movies': total_movies,
        'total_theaters': total_theaters,
        'total_screens': total_screens,
        'total_seats': total_seats,
        'today_showtimes': today_showtimes,
        'today_bookings': today_bookings,
        'active_reservations': active_reservations,
        'successful_payments': successful_payments,
        'pending_payments': pending_payments,
        'failed_payments': failed_payments,
        'expired_holds': expired_holds,
        'gross_revenue': gross_revenue,
        'refunds': refunds,
        'occupancy': occupancy,
        'date_from': date_from,
        'date_to': date_to,
        'selected_theatre': theatre_id,
        'selected_movie': movie_id,
        'selected_status': status_filter,
        'theatre_options': CinemaVenue.objects.filter(active=True).order_by('name'),
        'movie_options': Movie.objects.order_by('name'),
        'available_count': available_count,
        'reserved_count': reserved_count,
        'booked_count': booked_count,
        'blocked_count': blocked_count,
        'recent_bookings': recent_bookings,
        'recent_payments': recent_payments,
        'recent_activity': recent_activity[:8],
        'upcoming_showtimes': Theater.objects.filter(active=True, operational_status__in=['SCHEDULED', 'BOOKING_OPEN'], time__gte=now).select_related('movie', 'screen').order_by('time')[:8],
        'venues_data': venues_data,
        'title': 'TicketMitra Operations Center',
    }
    return render(request, 'admin/index.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_movies_view(request):
    """
    Full Movie Management with search, multi-filters, Add/Edit/Delete modals,
    and instantaneous 'Currently Showing' toggle reflecting immediately on the user website.
    """
    now = timezone.now()
    today = now.date()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'toggle_status':
            movie_id = request.POST.get('movie_id')
            movie = get_object_or_404(Movie, id=movie_id)
            movie.status = 'ENDED' if movie.status == 'CURRENT' else 'CURRENT'
            movie.save(update_fields=['status'])
            record_admin_activity(request, 'movie_status_changed', movie, {'status': movie.status})
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'new_status': movie.status, 'is_current': movie.status == 'CURRENT'})
            messages.success(request, f"Updated '{movie.get_display_title()}' status to {movie.get_status_display()}.")
            return redirect('/admin/movies/')

        elif action == 'add_movie':
            title = request.POST.get('title', '').strip()
            name = request.POST.get('name', title).strip() or title
            tmdb_id = request.POST.get('tmdb_id') or None
            release_date = request.POST.get('release_date') or None
            lang = request.POST.get('original_language', '').strip() or None
            runtime_value = request.POST.get('runtime', '').strip()
            runtime = int(runtime_value) if runtime_value else None
            age_cert = request.POST.get('age_certification', '').strip() or None
            rating_value = request.POST.get('rating', '').strip()
            rating = Decimal(rating_value) if rating_value else Decimal('0.0')
            trailer_url = request.POST.get('trailer_url', '').strip()
            description = request.POST.get('description', '').strip()
            is_showing = request.POST.get('is_showing') == 'on'

            movie = Movie.objects.create(
                title=title,
                name=name,
                tmdb_id=int(tmdb_id) if tmdb_id and str(tmdb_id).isdigit() else None,
                release_date=release_date,
                original_language=lang,
                runtime=runtime,
                age_certification=age_cert,
                rating=rating,
                tmdb_rating=rating,
                trailer_url=trailer_url,
                description=description,
                status='CURRENT' if is_showing else 'DRAFT'
            )
            if 'image' in request.FILES:
                movie.image = request.FILES['image']
                movie.save(update_fields=['image'])

            # Add genres
            genre_ids = request.POST.getlist('genres')
            if genre_ids:
                movie.genres.set(genre_ids)
            record_admin_activity(request, 'movie_created', movie, {'status': movie.status})

            messages.success(request, f"Movie '{movie.get_display_title()}' added successfully.")
            return redirect('/admin/movies/')

        elif action == 'edit_movie':
            movie_id = request.POST.get('movie_id')
            movie = get_object_or_404(Movie, id=movie_id)
            movie.title = request.POST.get('title', movie.title).strip()
            movie.name = movie.title
            if request.POST.get('release_date'):
                movie.release_date = request.POST.get('release_date')
            movie.original_language = request.POST.get('original_language', movie.original_language).strip()
            runtime_value = request.POST.get('runtime', '').strip()
            movie.runtime = int(runtime_value) if runtime_value else None
            movie.age_certification = request.POST.get('age_certification', '').strip() or None
            rating_value = request.POST.get('rating', '').strip()
            movie.rating = Decimal(rating_value) if rating_value else Decimal('0.0')
            movie.trailer_url = request.POST.get('trailer_url', movie.trailer_url).strip()
            movie.description = request.POST.get('description', movie.description).strip()
            is_showing = request.POST.get('is_showing') == 'on'
            movie.status = 'CURRENT' if is_showing else 'ENDED'

            if 'image' in request.FILES:
                movie.image = request.FILES['image']

            movie.save()
            genre_ids = request.POST.getlist('genres')
            if genre_ids:
                movie.genres.set(genre_ids)
            record_admin_activity(request, 'movie_updated', movie, {'status': movie.status})

            messages.success(request, f"Movie '{movie.get_display_title()}' updated successfully.")
            return redirect('/admin/movies/')

        elif action == 'delete_movie':
            movie_id = request.POST.get('movie_id')
            movie = get_object_or_404(Movie, id=movie_id)
            title = movie.get_display_title()
            record_admin_activity(request, 'movie_deleted', movie, {'title': title})
            movie.delete()
            messages.success(request, f"Movie '{title}' deleted from catalog.")
            return redirect('/admin/movies/')

    # Query & Filters
    q = request.GET.get('q', '').strip()
    selected_lang = request.GET.get('language', '').strip()
    selected_genre = request.GET.get('genre', '').strip()
    selected_showing = request.GET.get('showing', '').strip()
    selected_sort = request.GET.get('sort', 'newest').strip()

    movies = Movie.objects.prefetch_related('genres', 'languages')
    if q:
        movies = movies.filter(Q(title__icontains=q) | Q(name__icontains=q) | Q(cast__icontains=q) | Q(description__icontains=q))
    if selected_lang:
        movies = movies.filter(Q(original_language=selected_lang) | Q(languages__code=selected_lang))
    if selected_genre:
        if selected_genre.isdigit():
            movies = movies.filter(genres__id=int(selected_genre))
        else:
            movies = movies.filter(genres__name__iexact=selected_genre)

    if selected_showing == 'current':
        movies = movies.filter(status='CURRENT', release_date__lte=today)
    elif selected_showing == 'upcoming':
        movies = movies.filter(release_date__gt=today)
    elif selected_showing == 'ended':
        movies = movies.filter(status='ENDED')

    if selected_sort == 'rating':
        movies = movies.order_by('-rating', '-popularity')
    elif selected_sort == 'title':
        movies = movies.order_by('title', 'name')
    elif selected_sort == 'popularity':
        movies = movies.order_by('-popularity')
    else:
        movies = movies.order_by('-release_date', '-id')

    paginator = Paginator(movies.distinct(), 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    all_genres = Genre.objects.all().order_by('name')
    all_languages = Language.objects.all().order_by('name')

    context = {
        'page_obj': page_obj,
        'movies': page_obj,
        'total_count': paginator.count,
        'q': q,
        'selected_lang': selected_lang,
        'selected_genre': selected_genre,
        'selected_showing': selected_showing,
        'selected_sort': selected_sort,
        'all_genres': all_genres,
        'all_languages': all_languages,
        'title': 'Movie Catalog Management',
    }
    return render(request, 'admin/movies_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_theatres_view(request):
    """
    Visual Theatre Management with cinema cards, screen counts, seat counts,
    and Add/Edit/Deactivate actions.
    """
    # Sync existing distinct Theater names into CinemaVenue
    existing_venue_names = Theater.objects.values_list('name', flat=True).distinct()
    for v_name in existing_venue_names:
        sample_t = Theater.objects.filter(name=v_name).first()
        if sample_t and not CinemaVenue.objects.filter(name=v_name).exists():
            CinemaVenue.objects.create(
                name=v_name,
                address=sample_t.address or sample_t.location,
                city=sample_t.city,
                state=sample_t.state,
                pincode=sample_t.pincode,
                latitude=sample_t.latitude,
                longitude=sample_t.longitude,
                active=True
            )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_theatre':
            name = request.POST.get('name', '').strip()
            theatre_code = request.POST.get('theatre_code', '').strip().upper() or None
            address = request.POST.get('address', '').strip()
            city = request.POST.get('city', 'Bengaluru').strip()
            state = request.POST.get('state', 'Karnataka').strip()
            lat = request.POST.get('latitude') or None
            lon = request.POST.get('longitude') or None
            contact = request.POST.get('contact_number', '').strip()
            description = request.POST.get('description', '').strip()
            active = request.POST.get('active') == 'on'
            if not name:
                messages.error(request, 'Theatre name is required.')
                return redirect('/admin/theatres/')
            if theatre_code and CinemaVenue.objects.filter(theatre_code=theatre_code).exclude(name=name).exists():
                messages.error(request, f'Theatre code {theatre_code} is already in use.')
                return redirect('/admin/theatres/')

            status = request.POST.get('status', 'ACTIVE')
            closed_weekdays = [int(w) for w in request.POST.getlist('closed_weekdays') if w.isdigit()]
            venue, created = CinemaVenue.objects.get_or_create(
                name=name,
                defaults={
                    'address': address,
                    'city': city,
                    'state': state,
                    'latitude': Decimal(lat) if lat else None,
                    'longitude': Decimal(lon) if lon else None,
                    'contact_number': contact,
                    'description': description,
                    'active': active and status == 'ACTIVE',
                    'theatre_code': theatre_code,
                    'status': status,
                    'pincode': request.POST.get('pincode', '').strip(),
                    'opens_at': request.POST.get('opens_at') or None,
                    'closes_at': request.POST.get('closes_at') or None,
                    'closed_weekdays': closed_weekdays,
                }
            )
            if not created:
                venue.address = address
                venue.city = city
                venue.state = state
                venue.active = active and status == 'ACTIVE'
                venue.status = status
                venue.theatre_code = theatre_code or venue.theatre_code
                venue.contact_number = contact
                venue.description = description
                venue.pincode = request.POST.get('pincode', venue.pincode).strip()
                venue.opens_at = request.POST.get('opens_at') or None
                venue.closes_at = request.POST.get('closes_at') or None
                venue.closed_weekdays = closed_weekdays
                venue.save()
            record_admin_activity(request, 'theatre_saved', venue, {'created': created, 'active': venue.active})
            messages.success(request, f"Theatre '{name}' saved successfully.")
            return redirect('/admin/theatres/')

        elif action == 'edit_theatre':
            theatre_id = request.POST.get('theatre_id')
            venue = get_object_or_404(CinemaVenue, id=theatre_id)
            venue.name = request.POST.get('name', venue.name).strip()
            venue.theatre_code = request.POST.get('theatre_code', venue.theatre_code or '').strip().upper() or None
            venue.address = request.POST.get('address', venue.address).strip()
            venue.city = request.POST.get('city', venue.city).strip()
            venue.state = request.POST.get('state', venue.state).strip()
            lat = request.POST.get('latitude')
            lon = request.POST.get('longitude')
            if lat:
                venue.latitude = Decimal(lat)
            if lon:
                venue.longitude = Decimal(lon)
            venue.contact_number = request.POST.get('contact_number', venue.contact_number).strip()
            venue.description = request.POST.get('description', venue.description).strip()
            status = request.POST.get('status', 'ACTIVE')
            venue.status = status
            venue.active = (request.POST.get('active') == 'on') and (status == 'ACTIVE')
            venue.pincode = request.POST.get('pincode', venue.pincode).strip()
            venue.opens_at = request.POST.get('opens_at') or None
            venue.closes_at = request.POST.get('closes_at') or None
            if 'closed_weekdays' in request.POST:
                venue.closed_weekdays = [int(w) for w in request.POST.getlist('closed_weekdays') if w.isdigit()]
            venue.save()
            record_admin_activity(request, 'theatre_updated', venue, {'active': venue.active})
            messages.success(request, f"Theatre '{venue.name}' updated successfully.")
            return redirect('/admin/theatres/')

        elif action == 'toggle_theatre':
            theatre_id = request.POST.get('theatre_id')
            venue = get_object_or_404(CinemaVenue, id=theatre_id)
            venue.active = not venue.active
            venue.status = 'ACTIVE' if venue.active else 'INACTIVE'
            venue.save(update_fields=['active', 'status'])
            record_admin_activity(request, 'theatre_status_changed', venue, {'active': venue.active})
            messages.success(request, f"Theatre '{venue.name}' is now {'Active' if venue.active else 'Inactive'}.")
            return redirect('/admin/theatres/')

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    venues_qs = CinemaVenue.objects.all().order_by('name')
    if q:
        venues_qs = venues_qs.filter(
            Q(name__icontains=q) |
            Q(theatre_code__icontains=q) |
            Q(city__icontains=q) |
            Q(address__icontains=q)
        )
    if status_filter:
        venues_qs = venues_qs.filter(status=status_filter)

    theatres_data = []
    now = timezone.now()
    today = now.date()

    for v in venues_qs:
        screens = Screen.objects.filter(theater_name=v.name)
        sc_count = screens.count()
        total_seats = Seat.objects.filter(theater__name=v.name).count()
        today_shows = Theater.objects.filter(name=v.name, time__date=today).count()
        theatres_data.append({
            'venue': v,
            'screens_count': sc_count,
            'seats_count': total_seats,
            'today_shows': today_shows,
            'screens': screens[:5],
        })

    context = {
        'theatres_data': theatres_data,
        'total_count': len(theatres_data),
        'title': 'Cinema Theatre Management',
    }
    return render(request, 'admin/theatres_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_screens_view(request):
    """
    Screen Management: multiple screens per theatre (IMAX, 4DX, PXL, Gold, Standard, Custom).
    """
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_screen':
            theater_name = request.POST.get('theater_name', '').strip()
            name = request.POST.get('name', '').strip()
            screen_type = request.POST.get('screen_type', 'IMAX').strip()
            custom_type = request.POST.get('custom_screen_type', '').strip()
            if custom_type:
                screen_type = custom_type.upper()
            capacity = int(request.POST.get('capacity') or 32)
            active = request.POST.get('active') == 'on'
            operational_status = request.POST.get('operational_status', 'ACTIVE')
            if operational_status not in {'ACTIVE', 'INACTIVE', 'MAINTENANCE'}:
                operational_status = 'ACTIVE'
            if not theater_name or not name or capacity < 1:
                messages.error(request, 'Select a theatre and enter a screen name and positive capacity.')
                return redirect('/admin/screens/')

            screen, created = Screen.objects.get_or_create(
                theater_name=theater_name,
                name=name,
                defaults={
                    'screen_type': screen_type,
                    'capacity': capacity,
                    'active': active and operational_status == 'ACTIVE',
                    'screen_number': int(request.POST['screen_number']) if request.POST.get('screen_number', '').isdigit() else None,
                    'operational_status': operational_status,
                    'turnaround_minutes': int(request.POST.get('turnaround_minutes') or 30),
                }
            )
            if not created:
                screen.screen_type = screen_type
                screen.capacity = capacity
                screen.active = active and operational_status == 'ACTIVE'
                screen.operational_status = operational_status
                screen.screen_number = int(request.POST['screen_number']) if request.POST.get('screen_number', '').isdigit() else screen.screen_number
                screen.turnaround_minutes = int(request.POST.get('turnaround_minutes') or screen.turnaround_minutes)
                screen.save()
            record_admin_activity(request, 'screen_saved', screen, {'created': created, 'capacity': screen.capacity})

            messages.success(request, f"Screen '{name}' ({screen_type}) saved for {theater_name}.")
            return redirect(f"/admin/screens/?theatre={theater_name}")

        elif action == 'edit_screen':
            screen_id = request.POST.get('screen_id')
            screen = get_object_or_404(Screen, id=screen_id)
            screen.theater_name = request.POST.get('theater_name', screen.theater_name).strip()
            screen.name = request.POST.get('name', screen.name).strip()
            screen_type = request.POST.get('screen_type', screen.screen_type).strip()
            custom_type = request.POST.get('custom_screen_type', '').strip()
            if custom_type:
                screen_type = custom_type.upper()
            screen.screen_type = screen_type
            screen.capacity = int(request.POST.get('capacity') or screen.capacity or 32)
            screen.active = request.POST.get('active') == 'on'
            screen.operational_status = request.POST.get('operational_status', screen.operational_status)
            if screen.operational_status not in {'ACTIVE', 'INACTIVE', 'MAINTENANCE'}:
                screen.operational_status = 'ACTIVE'
            screen.active = screen.active and screen.operational_status == 'ACTIVE'
            if request.POST.get('screen_number', '').isdigit():
                screen.screen_number = int(request.POST['screen_number'])
            screen.turnaround_minutes = int(request.POST.get('turnaround_minutes') or screen.turnaround_minutes)
            screen.save()
            record_admin_activity(request, 'screen_updated', screen, {'capacity': screen.capacity, 'active': screen.active})
            messages.success(request, f"Screen '{screen.name}' updated successfully.")
            return redirect(f"/admin/screens/?theatre={screen.theater_name}")

        elif action == 'delete_screen':
            screen_id = request.POST.get('screen_id')
            screen = get_object_or_404(Screen, id=screen_id)
            th_name = screen.theater_name
            if Theater.objects.filter(screen=screen, time__gte=timezone.now()).exists() or Booking.objects.filter(theater__screen=screen).exists():
                messages.error(request, 'This screen has future showtimes or booking history. Deactivate it instead of deleting it.')
                return redirect(f"/admin/screens/?theatre={th_name}")
            screen.delete()
            record_admin_activity(request, 'screen_deleted', screen, {'theatre': th_name})
            messages.success(request, "Screen deleted.")
            return redirect(f"/admin/screens/?theatre={th_name}")

    selected_theatre = request.GET.get('theatre', '').strip()
    screens_qs = Screen.objects.all().order_by('theater_name', 'name')
    if selected_theatre:
        screens_qs = screens_qs.filter(theater_name=selected_theatre)

    all_theatres = CinemaVenue.objects.filter(active=True).values_list('name', flat=True)
    if not all_theatres:
        all_theatres = Theater.objects.values_list('name', flat=True).distinct()

    screens_data = []
    for sc in screens_qs:
        seats_count = Seat.objects.filter(screen=sc).count()
        shows_count = Theater.objects.filter(screen=sc).count()
        screens_data.append({
            'screen': sc,
            'seats_count': seats_count,
            'shows_count': shows_count,
        })

    context = {
        'screens_data': screens_data,
        'selected_theatre': selected_theatre,
        'all_theatres': sorted(set(all_theatres)),
        'title': 'Auditorium & Screen Management',
    }
    return render(request, 'admin/screens_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_showtimes_view(request):
    """
    Showtime Management: schedule movies into theatres and screens with dates,
    start times, formats, and ticket prices. Immediately updates user booking pages.
    """
    now = timezone.now()
    today = now.date()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_showtime':
            movie_id = request.POST.get('movie_id')
            theater_name = request.POST.get('theater_name', '').strip()
            screen_id = request.POST.get('screen_id')
            show_date = request.POST.get('show_date') or today.isoformat()
            show_time_str = request.POST.get('show_time', '19:30')
            price = request.POST.get('price', '250.00')

            movie = get_object_or_404(Movie, id=movie_id)
            screen = get_object_or_404(Screen, id=screen_id) if screen_id else None

            if not movie.is_in_active_catalog or movie.status not in {'CURRENT', 'ADVANCE_BOOKING', 'UPCOMING'}:
                messages.error(request, 'This movie is inactive or unavailable for theatrical scheduling.')
                return redirect('/admin/showtimes/')
            if screen is None:
                messages.error(request, 'Choose a screen before publishing a showtime.')
                return redirect('/admin/showtimes/')
            venue = CinemaVenue.objects.filter(name=theater_name).first()
            if venue is None:
                venue = CinemaVenue.objects.create(name=theater_name, theatre_code=f'TM-{screen.id}', active=True, status='ACTIVE')
            if not venue.active or venue.status != 'ACTIVE':
                messages.error(request, 'Choose an active theatre.')
                return redirect('/admin/showtimes/')
            if screen.operational_status != 'ACTIVE' or not screen.active:
                messages.error(request, 'The selected screen is inactive or under maintenance.')
                return redirect('/admin/showtimes/')

            # Validation: Screen must belong to the selected theatre
            if screen and screen.theater_name != theater_name:
                messages.error(request, f"Screen '{screen.name}' belongs to '{screen.theater_name}', not '{theater_name}'.")
                return redirect('/admin/showtimes/')

            # Parse datetime
            try:
                combined_dt = datetime.strptime(f"{show_date} {show_time_str}", "%Y-%m-%d %H:%M")
                aware_dt = timezone.make_aware(combined_dt) if timezone.is_naive(combined_dt) else combined_dt
                base_price = Decimal(str(price))
                if base_price < 0:
                    raise ValueError('Price cannot be negative.')
            except Exception as exc:
                messages.error(request, f'Invalid showtime date, time, or price: {exc}')
                return redirect('/admin/showtimes/')

            local_start = timezone.localtime(aware_dt)
            if venue.closed_weekdays and local_start.weekday() in venue.closed_weekdays:
                messages.error(request, 'The theatre is closed on the selected weekday.')
                return redirect('/admin/showtimes/')
            if venue.opens_at and venue.closes_at:
                duration = movie.runtime or 120
                local_end = (local_start + timedelta(minutes=duration)).time()
                if local_start.time() < venue.opens_at or local_end > venue.closes_at:
                    messages.error(request, 'The show duration falls outside theatre operating hours.')
                    return redirect('/admin/showtimes/')
            if movie.release_date and local_start.date() < movie.release_date and not movie.is_advance_booking_open:
                messages.error(request, 'This movie is not yet available for advance booking on that date.')
                return redirect('/admin/showtimes/')

            # Get venue address details
            address = venue.address if venue else ''
            city = venue.city if venue else 'Bengaluru'
            state = venue.state if venue else 'Karnataka'
            pincode = venue.pincode if venue else ''
            lat = venue.latitude if venue else None
            lon = venue.longitude if venue else None

            raw_prices = request.POST.get('ticket_prices_json', '').strip()
            try:
                category_prices = json.loads(raw_prices) if raw_prices else {}
                if not isinstance(category_prices, dict):
                    raise TypeError('Category prices must be a JSON object.')
                category_prices = {str(k).upper(): str(Decimal(str(v))) for k, v in category_prices.items()}
                if any(Decimal(v) < 0 for v in category_prices.values()):
                    raise ValueError('Category prices cannot be negative.')
            except Exception as exc:
                messages.error(request, f'Invalid category prices: {exc}')
                return redirect('/admin/showtimes/')
            # Check if pricing plan was chosen
            plan_id = request.POST.get('pricing_plan_id')
            if plan_id:
                sel_plan = PricingPlan.objects.filter(id=plan_id).first()
                if sel_plan and sel_plan.category_prices:
                    category_prices = dict(sel_plan.category_prices)
                    base_price = Decimal(str(sel_plan.base_price))

            category_prices.setdefault('REGULAR', str(base_price))
            category_prices.setdefault('PREMIUM', str(base_price))
            category_prices.setdefault('VIP', str(base_price))

            op_status = request.POST.get('operational_status', 'BOOKING_OPEN').strip()
            is_active = (op_status in {'BOOKING_OPEN', 'SCHEDULED'})

            showtime = Theater(
                name=theater_name,
                movie=movie,
                screen=screen,
                time=aware_dt,
                location=address or f"{theater_name}, {city}",
                address=address,
                city=city,
                state=state,
                pincode=pincode,
                latitude=lat,
                longitude=lon,
                price=base_price,
                ticket_prices=category_prices,
                language=request.POST.get('language', '').strip(),
                subtitles_available=request.POST.get('subtitles_available') == 'on',
                operational_status=op_status,
                active=is_active
            )
            try:
                showtime.full_clean()
                showtime.save()
            except Exception as exc:
                details = getattr(exc, 'message_dict', None)
                messages.error(request, '; '.join(message for error_list in details.values() for message in error_list) if details else str(exc))
                return redirect('/admin/showtimes/')
            record_admin_activity(request, 'showtime_created', showtime, {'screen': screen.name, 'price': str(base_price), 'ticket_prices': category_prices})

            # Automatically generate standard 32 available seats for this new showtime
            layout = list(Seat.objects.filter(screen=screen).values('row', 'seat_number', 'seat_type').distinct().order_by('row', 'seat_number'))
            if not layout:
                layout = []
            capacity = screen.capacity or 32
            layout_names = {entry['seat_number'] for entry in layout}
            index = 0
            while len(layout) < capacity:
                row_index, seat_index = divmod(index, 10)
                row_name = chr(ord('A') + row_index)
                seat_name = f'{row_name}{seat_index + 1}'
                index += 1
                if seat_name in layout_names:
                    continue
                category = 'REGULAR' if row_index < 3 else ('PREMIUM' if row_index < 5 else 'VIP')
                layout.append({'row': row_name, 'seat_number': seat_name, 'seat_type': category})
                layout_names.add(seat_name)
            for seat_spec in layout[:capacity]:
                Seat.objects.get_or_create(
                    theater=showtime,
                    seat_number=seat_spec['seat_number'],
                    defaults={
                        'screen': screen,
                        'row': seat_spec['row'],
                        'seat_type': seat_spec['seat_type'],
                        'is_booked': False,
                        'is_blocked': False,
                    }
                )

            messages.success(request, f"Showtime for '{movie.get_display_title()}' at {theater_name} ({aware_dt.strftime('%b %d, %I:%M %p')}) created with 32 available seats.")
            return redirect('/admin/showtimes/')

        elif action == 'generate_recurring_showtimes':
            movie_id = request.POST.get('movie_id')
            theater_name = request.POST.get('theater_name', '').strip()
            screen_id = request.POST.get('screen_id')
            start_date_str = request.POST.get('start_date')
            end_date_str = request.POST.get('end_date')
            time_slots_str = request.POST.get('time_slots', '11:00, 14:30, 18:00, 21:15')
            language = request.POST.get('language', '').strip()
            subtitles_available = request.POST.get('subtitles_available') == 'on'
            base_price_override = request.POST.get('base_price')

            movie = get_object_or_404(Movie, id=movie_id)
            screen = get_object_or_404(Screen, id=screen_id) if screen_id else None
            venue = CinemaVenue.objects.filter(name=theater_name).first()

            if not screen or screen.operational_status != 'ACTIVE':
                messages.error(request, "Selected screen is inactive or unavailable.")
                return redirect('/admin/showtimes/')

            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if start_date > end_date:
                    raise ValueError("End date must be on or after start date.")
            except Exception as exc:
                messages.error(request, f"Invalid date range: {exc}")
                return redirect('/admin/showtimes/')

            slots = [s.strip() for s in time_slots_str.split(',') if s.strip()]
            if not slots:
                messages.error(request, "At least one time slot is required (e.g. 11:00, 18:00).")
                return redirect('/admin/showtimes/')

            created_shows = 0
            skipped_conflicts = 0
            cur_date = start_date
            while cur_date <= end_date:
                if venue and venue.closed_weekdays and cur_date.weekday() in venue.closed_weekdays:
                    cur_date += timedelta(days=1)
                    continue

                for slot_str in slots:
                    try:
                        slot_time = datetime.strptime(slot_str, '%H:%M').time()
                        show_dt = timezone.make_aware(datetime.combine(cur_date, slot_time))
                    except (ValueError, TypeError) as exc:
                        logger.debug(f"Skipping invalid slot '{slot_str}': {exc}")
                        continue

                    if venue and venue.opens_at and venue.closes_at:
                        dur = movie.runtime or 120
                        end_t = (show_dt + timedelta(minutes=dur)).time()
                        if slot_time < venue.opens_at or end_t > venue.closes_at:
                            skipped_conflicts += 1
                            continue

                    runtime = movie.runtime or 120
                    show_end = show_dt + timedelta(minutes=runtime)
                    buffer_min = screen.turnaround_minutes or 30
                    conflict = False
                    for existing in Theater.objects.filter(screen=screen, active=True, time__date=cur_date):
                        ex_dur = existing.movie.runtime or 120
                        ex_end = existing.time + timedelta(minutes=ex_dur + (screen.turnaround_minutes or 30))
                        if show_dt < ex_end and show_end + timedelta(minutes=buffer_min) > existing.time:
                            conflict = True
                            break
                    if conflict:
                        skipped_conflicts += 1
                        continue

                    effective_plan = PricingPlan.resolve_plan_for_showtime(
                        Theater(name=theater_name, movie=movie, screen=screen, time=show_dt)
                    )
                    cat_prices = {}
                    if effective_plan and effective_plan.category_prices:
                        cat_prices = dict(effective_plan.category_prices)
                    elif base_price_override:
                        bp = float(base_price_override)
                        cat_prices = {
                            'REGULAR': bp,
                            'PREMIUM': round(bp * 1.35, 2),
                            'RECLINER': round(bp * 1.8, 2),
                            'VIP': round(bp * 2.2, 2),
                            'ACCESSIBLE': round(bp * 0.9, 2),
                        }
                    else:
                        cat_prices = {
                            'REGULAR': 180.00,
                            'PREMIUM': 250.00,
                            'RECLINER': 350.00,
                            'VIP': 450.00,
                            'ACCESSIBLE': 150.00,
                        }

                    show_obj = Theater.objects.create(
                        name=theater_name,
                        movie=movie,
                        screen=screen,
                        time=show_dt,
                        location=venue.address if venue else f"{theater_name}, Bengaluru",
                        address=venue.address if venue else '',
                        city=venue.city if venue else 'Bengaluru',
                        state=venue.state if venue else 'Karnataka',
                        pincode=venue.pincode if venue else '',
                        latitude=venue.latitude if venue else None,
                        longitude=venue.longitude if venue else None,
                        price=Decimal(str(cat_prices.get('REGULAR', 180.00))),
                        ticket_prices=cat_prices,
                        language=language or movie.original_language or 'en',
                        subtitles_available=subtitles_available,
                        active=True,
                    )

                    layout = list(Seat.objects.filter(screen=screen).values('row', 'seat_number', 'seat_type').distinct().order_by('row', 'seat_number'))
                    capacity = screen.capacity or 32
                    if not layout:
                        layout = []
                        index = 0
                        while len(layout) < capacity:
                            r_idx, s_idx = divmod(index, 8)
                            r_name = chr(ord('A') + r_idx)
                            s_name = f"{r_name}{s_idx + 1}"
                            cat = 'REGULAR' if r_idx < 2 else ('PREMIUM' if r_idx < 4 else 'VIP')
                            layout.append({'row': r_name, 'seat_number': s_name, 'seat_type': cat})
                            index += 1

                    for seat_spec in layout[:capacity]:
                        Seat.objects.get_or_create(
                            theater=show_obj,
                            seat_number=seat_spec['seat_number'],
                            defaults={
                                'screen': screen,
                                'row': seat_spec['row'],
                                'seat_type': seat_spec['seat_type'],
                                'is_booked': False,
                                'is_blocked': False,
                            }
                        )
                    created_shows += 1

                cur_date += timedelta(days=1)

            record_admin_activity(request, 'recurring_showtimes_generated', screen, {
                'created_count': created_shows,
                'skipped_conflicts': skipped_conflicts,
                'start_date': str(start_date),
                'end_date': str(end_date),
            })
            messages.success(request, f"Generated {created_shows} recurring showtimes for '{movie.get_display_title()}' in screen {screen.name} ({start_date} to {end_date}). Skipped {skipped_conflicts} conflict/closed slot(s).")
            return redirect('/admin/showtimes/')

        elif action == 'edit_showtime':
            showtime_id = request.POST.get('showtime_id')
            showtime = get_object_or_404(Theater, id=showtime_id)
            new_status = request.POST.get('operational_status', showtime.operational_status)
            showtime.operational_status = new_status
            showtime.active = (new_status in {'BOOKING_OPEN', 'SCHEDULED'})
            if request.POST.get('price'):
                try:
                    showtime.price = Decimal(str(request.POST['price']))
                except Exception:
                    pass
            if request.POST.get('language'):
                showtime.language = request.POST['language'].strip()
            showtime.subtitles_available = (request.POST.get('subtitles_available') == 'on')
            showtime.save()
            record_admin_activity(request, 'showtime_updated', showtime, {'status': new_status, 'active': showtime.active})
            messages.success(request, f"Showtime #{showtime.id} updated successfully.")
            return redirect('/admin/showtimes/')

        elif action == 'delete_showtime':
            showtime_id = request.POST.get('showtime_id')
            showtime = get_object_or_404(Theater, id=showtime_id)
            showtime.active = False
            showtime.operational_status = 'CANCELLED'
            showtime.save(update_fields=['active', 'operational_status'])
            for hold in SeatReservation.objects.filter(theater=showtime, status='ACTIVE'):
                hold.status = 'CANCELLED'
                hold.seats.clear()
                hold.save(update_fields=['status'])
            record_admin_activity(request, 'showtime_cancelled', showtime, {'bookings_retained': Booking.objects.filter(theater=showtime).count()})
            messages.success(request, "Showtime cancelled. Existing booking records were retained and active seat holds released.")
            return redirect('/admin/showtimes/')

    # Filters
    selected_movie_id = request.GET.get('movie_id')
    selected_theatre = request.GET.get('theatre', '').strip()
    selected_date = request.GET.get('date', '').strip()
    selected_status = request.GET.get('status', '').strip()

    showtimes_qs = Theater.objects.select_related('movie', 'screen').order_by('-time')
    if selected_movie_id:
        showtimes_qs = showtimes_qs.filter(movie_id=selected_movie_id)
    if selected_theatre:
        showtimes_qs = showtimes_qs.filter(name=selected_theatre)
    if selected_date:
        showtimes_qs = showtimes_qs.filter(time__date=selected_date)
    if selected_status:
        showtimes_qs = showtimes_qs.filter(operational_status=selected_status)

    paginator = Paginator(showtimes_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    all_movies = Movie.objects.filter(status='CURRENT').order_by('title', 'name')
    if not all_movies.exists():
        all_movies = Movie.objects.all().order_by('name')

    all_theatres = CinemaVenue.objects.filter(active=True).order_by('name')
    all_screens = Screen.objects.filter(active=True).order_by('theater_name', 'name')

    view_mode = request.GET.get('view', 'list').strip()
    calendar_days = []
    calendar_data = {}

    ref_date = today
    if selected_date:
        try:
            ref_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            pass

    start_of_week = ref_date - timedelta(days=ref_date.weekday())
    for d in range(7):
        day_d = start_of_week + timedelta(days=d)
        calendar_days.append(day_d)
        calendar_data[day_d.isoformat()] = list(
            Theater.objects.filter(time__date=day_d, active=True)
            .select_related('movie', 'screen')
            .order_by('time')
        )

    context = {
        'page_obj': page_obj,
        'showtimes': page_obj,
        'all_movies': all_movies,
        'all_theatres': all_theatres,
        'all_screens': all_screens,
        'selected_movie_id': selected_movie_id,
        'selected_theatre': selected_theatre,
        'selected_date': selected_date,
        'selected_status': selected_status,
        'all_pricing_plans': PricingPlan.objects.filter(is_active=True).order_by('-start_date'),
        'view_mode': view_mode,
        'calendar_days': calendar_days,
        'calendar_data': calendar_data,
        'ref_date': ref_date,
        'today': today,
        'title': 'Showtime Management',
    }
    return render(request, 'admin/showtimes_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_bookings_view(request):
    """
    Booking Management: real-time confirmed booking logs, seat references,
    and cancellation operations.
    """
    now = timezone.now()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cancel_booking':
            booking_id = request.POST.get('booking_id')
            reason = request.POST.get('refund_reason', 'Cancelled by administrator')
            process_refund = request.POST.get('process_refund') == '1'
            booking = get_object_or_404(Booking, id=booking_id)

            if process_refund:
                booking.cancel(refund=True)
                booking.refund_amount = booking.amount
                booking.save(update_fields=['status', 'cancelled_at', 'refund_amount'])

                # Find associated payment
                payment = Payment.objects.filter(Q(booking=booking) | Q(bookings=booking)).first()
                if payment and payment.status != 'REFUNDED':
                    payment.status = 'REFUNDED'
                    payment.failure_reason = f"Refunded: {reason}"
                    payment.save(update_fields=['status', 'failure_reason'])
                record_admin_activity(request, 'booking_cancelled_refunded', booking, {'refund_amount': str(booking.amount), 'reason': reason})
                messages.success(request, f"Booking #{booking.id} cancelled with refund of ₹{booking.amount}. Seat {booking.seat.seat_number} is now released.")
            else:
                booking.cancel(refund=False)
                record_admin_activity(request, 'booking_cancelled', booking, {'refund_status': 'not_processed', 'reason': reason})
                messages.success(request, f"Booking #{booking.id} cancelled without refund. Seat {booking.seat.seat_number} is now released.")
            return redirect('/admin/bookings/')
        if action == 'check_in_booking':
            booking_id = request.POST.get('booking_id')
            booking = get_object_or_404(Booking, id=booking_id)
            if booking.attended_at:
                messages.info(request, f"Booking #{booking.id} already has a verified check-in.")
            else:
                try:
                    booking.check_in_attendee()
                    record_admin_activity(request, 'attendee_checked_in', booking, {})
                    messages.success(request, f"Booking #{booking.id} checked in. The attendee is now eligible to review.")
                except ValueError as exc:
                    messages.error(request, str(exc))
            return redirect('/admin/bookings/')
        if action == 'undo_check_in':
            booking_id = request.POST.get('booking_id')
            booking = get_object_or_404(Booking, id=booking_id)
            if booking.attended_at:
                booking.attended_at = None
                booking.save(update_fields=['attended_at'])
                messages.success(request, f"Check-in for booking #{booking.id} was removed.")
            return redirect('/admin/bookings/')

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    bookings = Booking.objects.select_related('user', 'movie', 'theater', 'theater__screen', 'seat').order_by('-booked_at')
    if q:
        bookings = bookings.filter(
            Q(id__icontains=q) |
            Q(user__username__icontains=q) |
            Q(user__email__icontains=q) |
            Q(movie__title__icontains=q) |
            Q(movie__name__icontains=q) |
            Q(seat__seat_number__icontains=q)
        )
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    paginator = Paginator(bookings, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'bookings': page_obj,
        'q': q,
        'status_filter': status_filter,
        'total_count': paginator.count,
        'now': now,
        'title': 'Booking Management',
    }
    return render(request, 'admin/bookings_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_reservations_view(request):
    """
    Seat Reservation Management: live 2-minute seat hold inspection,
    countdown timers, and reservation status tracking.
    """
    now = timezone.now()
    cleanup_expired_reservations()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cancel_reservation':
            res_id = request.POST.get('reservation_id')
            res = get_object_or_404(SeatReservation, id=res_id)
            res.status = 'CANCELLED'
            res.seats.clear()
            res.save(update_fields=['status'])
            messages.success(request, f"Reservation #{res.id} cancelled and seats released.")
            return redirect('/admin/reservations/')

    status_filter = request.GET.get('status', '').strip()
    reservations = SeatReservation.objects.select_related('user', 'theater', 'theater__movie', 'theater__screen').prefetch_related('seats').order_by('-created_at')

    if status_filter:
        reservations = reservations.filter(status=status_filter)

    paginator = Paginator(reservations, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'reservations': page_obj,
        'status_filter': status_filter,
        'now': now,
        'total_count': paginator.count,
        'title': 'Seat Reservations Management',
    }
    return render(request, 'admin/reservations_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_payments_view(request):
    """
    Payment Management: full Stripe and direct payment transaction logs
    with status badges, amount, order/payment reference, detail inspection,
    and refund processing through Stripe.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'refund_payment':
            payment_id = request.POST.get('payment_id')
            reason = request.POST.get('refund_reason', 'Customer requested cancellation')
            payment = get_object_or_404(Payment, id=payment_id)

            if payment.status == 'REFUNDED':
                messages.warning(request, f"Payment #{payment.id} is already refunded.")
                return redirect('/admin/payments/')

            stripe_refund_id = None
            try:
                import stripe
                from django.conf import settings
                stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '') or 'sk_test_placeholder'
                if payment.order_id and (payment.order_id.startswith('pi_') or payment.order_id.startswith('ch_')):
                    if not stripe.api_key.startswith('sk_test_placeholder'):
                        try:
                            rf = stripe.Refund.create(payment_intent=payment.order_id, reason='requested_by_customer')
                            stripe_refund_id = rf.id
                        except Exception:
                            stripe_refund_id = f"rf_sim_{payment.order_id[:16]}"
                    else:
                        stripe_refund_id = f"rf_test_{payment.order_id[:16]}"
                else:
                    stripe_refund_id = f"rf_manual_{payment.id}"
            except Exception:
                stripe_refund_id = f"rf_local_{payment.id}"

            payment.status = 'REFUNDED'
            payment.failure_reason = f"Refunded: {reason} (Ref: {stripe_refund_id})"
            payment.save(update_fields=['status', 'failure_reason'])

            refunded_seats = []
            if payment.booking:
                payment.booking.cancel(refund=True)
                payment.booking.refund_amount = payment.booking.amount
                payment.booking.save(update_fields=['status', 'cancelled_at', 'refund_amount'])
                if payment.booking.seat:
                    refunded_seats.append(payment.booking.seat.seat_number)

            for b in payment.bookings.all():
                b.cancel(refund=True)
                b.refund_amount = b.amount
                b.save(update_fields=['status', 'cancelled_at', 'refund_amount'])
                if b.seat:
                    refunded_seats.append(b.seat.seat_number)

            record_admin_activity(request, 'payment_refunded', payment, {
                'amount': str(payment.amount),
                'reason': reason,
                'stripe_refund_id': stripe_refund_id,
                'seats_released': refunded_seats,
            })
            messages.success(request, f"Payment #{payment.id} (₹{payment.amount}) has been refunded. Associated seat(s) {', '.join(refunded_seats) or 'N/A'} are now released.")
            return redirect('/admin/payments/')

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    payments = Payment.objects.select_related('user', 'booking', 'booking__movie', 'booking__theater').order_by('-created_at')
    if q:
        payments = payments.filter(
            Q(order_id__icontains=q) |
            Q(payment_id__icontains=q) |
            Q(transaction_id__icontains=q) |
            Q(user__username__icontains=q) |
            Q(user__email__icontains=q)
        )
    if status_filter:
        payments = payments.filter(status=status_filter)

    paginator = Paginator(payments, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'payments': page_obj,
        'q': q,
        'status_filter': status_filter,
        'total_count': paginator.count,
        'title': 'Payment & Transaction Management',
    }
    return render(request, 'admin/payments_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_users_view(request):
    """
    User Management: user accounts, bookings count, reviews count,
    active status, and account disable/enable controls.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle_user':
            user_id = request.POST.get('user_id')
            user_obj = get_object_or_404(User, id=user_id)
            if user_obj.is_superuser:
                messages.error(request, "Superuser accounts cannot be disabled.")
            else:
                user_obj.is_active = not user_obj.is_active
                user_obj.save(update_fields=['is_active'])
                record_admin_activity(request, 'customer_account_status_changed', user_obj, {'is_active': user_obj.is_active})
                messages.success(request, f"User '{user_obj.username}' is now {'Active' if user_obj.is_active else 'Disabled'}.")
            return redirect('/admin/users/')

    q = request.GET.get('q', '').strip()
    users_qs = User.objects.annotate(
        bookings_count=Count('booking', distinct=True),
        reviews_count=Count('movie_reviews', distinct=True)
    ).order_by('-date_joined')

    if q:
        users_qs = users_qs.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    paginator = Paginator(users_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'users': page_obj,
        'q': q,
        'total_count': paginator.count,
        'title': 'User Account Management',
    }
    return render(request, 'admin/users_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_reviews_view(request):
    """
    Review Management: moderate user ratings and reviews, verified viewer badges,
    approve, hide, and delete actions.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        review_id = request.POST.get('review_id')
        review = get_object_or_404(Review, id=review_id)

        if action == 'approve':
            review.is_reported = False
            review.report_count = 0
            review.reports.all().delete()
            review.save(update_fields=['is_reported', 'report_count'])
            messages.success(request, f"Review #{review.id} approved.")
        elif action == 'hide':
            review.is_reported = True
            review.save(update_fields=['is_reported'])
            messages.success(request, f"Review #{review.id} flagged and hidden.")
        elif action == 'delete':
            record_admin_activity(request, 'review_deleted', review, {'rating': review.rating})
            review.delete()
            messages.success(request, "Review deleted permanently.")
        if action in {'approve', 'hide'}:
            record_admin_activity(request, 'review_approved' if action == 'approve' else 'review_hidden', review, {'is_reported': review.is_reported, 'rating': review.rating})
        return redirect('/admin/reviews/')

    reviews_qs = Review.objects.select_related('user', 'movie', 'booking').order_by('-created_at')
    paginator = Paginator(reviews_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'reviews': page_obj,
        'total_count': paginator.count,
        'title': 'Audience Reviews Moderation',
    }
    return render(request, 'admin/reviews_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_reports_view(request):
    """
    Review Reports: flagged reviews reported by users for moderation.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        report_id = request.POST.get('report_id')
        report = get_object_or_404(ReviewReport.objects.select_related('review'), id=report_id)

        if action == 'dismiss':
            review = report.review
            report.delete()
            review.report_count = review.reports.count()
            if review.report_count == 0:
                review.is_reported = False
            review.save(update_fields=['report_count', 'is_reported'])
            messages.success(request, "Report dismissed.")
        elif action == 'delete_review':
            review = report.review
            report.delete()
            review.delete()
            messages.success(request, "Reported review deleted permanently.")
        return redirect('/admin/reports/')

    reports_qs = ReviewReport.objects.select_related('review', 'review__user', 'review__movie', 'reported_by').order_by('-created_at')
    paginator = Paginator(reports_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'reports': page_obj,
        'total_count': paginator.count,
        'title': 'Review Reports Moderation',
    }
    return render(request, 'admin/reports_list.html', context)


@staff_member_required(login_url='/admin/login/')
def admin_pricing_view(request):
    """
    Weekly & Date-Based Ticket Pricing Management (Requirement 5):
    Configure dynamic date-based ticket pricing plans, category prices (Regular, Premium,
    Recliner, VIP, Accessible), day-of-week rules (weekday vs weekend), screen type rules,
    bulk apply to future showtimes in date range, pricing audit log, and promotional coupons.
    """
    today = timezone.now().date()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action in ['create_plan', 'edit_plan']:
            plan_id = request.POST.get('plan_id')
            name = request.POST.get('name', '').strip()
            theatre_name = request.POST.get('theatre_name', '').strip()
            screen_type = request.POST.get('screen_type', 'ALL').strip()
            movie_id = request.POST.get('movie_id')
            start_date_str = request.POST.get('start_date')
            end_date_str = request.POST.get('end_date')
            day_type = request.POST.get('day_type', 'ALL')
            base_price = request.POST.get('base_price', '180.00')

            reg_price = request.POST.get('price_regular') or base_price
            prem_price = request.POST.get('price_premium') or str(round(float(base_price) * 1.35, 2))
            recl_price = request.POST.get('price_recliner') or str(round(float(base_price) * 1.8, 2))
            vip_price = request.POST.get('price_vip') or str(round(float(base_price) * 2.2, 2))
            acc_price = request.POST.get('price_accessible') or str(round(float(base_price) * 0.9, 2))

            category_prices = {
                'REGULAR': float(reg_price),
                'PREMIUM': float(prem_price),
                'RECLINER': float(recl_price),
                'VIP': float(vip_price),
                'ACCESSIBLE': float(acc_price),
            }

            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if start_date > end_date:
                    raise ValueError("End date must be on or after start date.")
                b_price = Decimal(str(base_price))
            except Exception as exc:
                messages.error(request, f"Invalid pricing plan parameters: {exc}")
                return redirect('/admin/pricing/')

            movie = Movie.objects.filter(id=movie_id).first() if movie_id else None

            if action == 'edit_plan' and plan_id:
                plan = get_object_or_404(PricingPlan, id=plan_id)
                old_data = {
                    'name': plan.name,
                    'start_date': str(plan.start_date),
                    'end_date': str(plan.end_date),
                    'category_prices': plan.category_prices,
                }
                plan.name = name or f"Plan {start_date} to {end_date}"
                plan.theatre_name = theatre_name
                plan.screen_type = screen_type
                plan.movie = movie
                plan.start_date = start_date
                plan.end_date = end_date
                plan.day_type = day_type
                plan.base_price = b_price
                plan.category_prices = category_prices
                plan.save()

                PricingHistory.objects.create(
                    plan=plan,
                    action='UPDATE_PLAN',
                    changed_by=request.user,
                    old_prices=old_data,
                    new_prices=category_prices,
                    details=f"Updated pricing plan '{plan.name}'"
                )
                record_admin_activity(request, 'pricing_plan_updated', plan, {'category_prices': category_prices})
                messages.success(request, f"Pricing plan '{plan.name}' updated successfully.")
            else:
                plan = PricingPlan.objects.create(
                    name=name or f"Plan {start_date} to {end_date}",
                    theatre_name=theatre_name,
                    screen_type=screen_type,
                    movie=movie,
                    start_date=start_date,
                    end_date=end_date,
                    day_type=day_type,
                    base_price=b_price,
                    category_prices=category_prices,
                    is_active=True,
                    created_by=request.user,
                )
                PricingHistory.objects.create(
                    plan=plan,
                    action='CREATE_PLAN',
                    changed_by=request.user,
                    old_prices={},
                    new_prices=category_prices,
                    details=f"Created pricing plan '{plan.name}' ({start_date} to {end_date})"
                )
                record_admin_activity(request, 'pricing_plan_created', plan, {'category_prices': category_prices})
                messages.success(request, f"Pricing plan '{plan.name}' created successfully.")

            if request.POST.get('bulk_apply_now') == '1':
                applied_count = plan.apply_to_future_showtimes(user=request.user)
                messages.info(request, f"Bulk applied plan pricing to {applied_count} matching future showtime(s). Existing bookings remained untouched.")

            return redirect('/admin/pricing/')

        elif action == 'toggle_plan':
            plan_id = request.POST.get('plan_id')
            plan = get_object_or_404(PricingPlan, id=plan_id)
            plan.is_active = not plan.is_active
            plan.save(update_fields=['is_active'])
            PricingHistory.objects.create(
                plan=plan,
                action='TOGGLE_PLAN',
                changed_by=request.user,
                details=f"Set active={plan.is_active} for plan '{plan.name}'"
            )
            messages.success(request, f"Plan '{plan.name}' is now {'Active' if plan.is_active else 'Disabled'}.")
            return redirect('/admin/pricing/')

        elif action == 'bulk_apply_plan':
            plan_id = request.POST.get('plan_id')
            plan = get_object_or_404(PricingPlan, id=plan_id)
            applied_count = plan.apply_to_future_showtimes(user=request.user)
            record_admin_activity(request, 'pricing_bulk_applied', plan, {'applied_count': applied_count})
            messages.success(request, f"Successfully applied '{plan.name}' to {applied_count} future showtime(s). Existing customer bookings were preserved.")
            return redirect('/admin/pricing/')

        elif action == 'delete_plan':
            plan_id = request.POST.get('plan_id')
            plan = get_object_or_404(PricingPlan, id=plan_id)
            p_name = plan.name
            PricingHistory.objects.create(
                plan=None,
                action='DELETE_PLAN',
                changed_by=request.user,
                details=f"Deleted plan '{p_name}'"
            )
            plan.delete()
            messages.success(request, f"Pricing plan '{p_name}' deleted.")
            return redirect('/admin/pricing/')

        elif action == 'create_coupon':
            code = (request.POST.get('code') or '').strip().upper()
            description = (request.POST.get('description') or '').strip()
            discount_type = request.POST.get('discount_type', 'PERCENTAGE')
            discount_value = Decimal(request.POST.get('discount_value', '10.00'))
            min_amount = Decimal(request.POST.get('min_amount', '0.00'))
            max_discount_raw = request.POST.get('max_discount')
            max_discount = Decimal(max_discount_raw) if max_discount_raw else None
            valid_from = request.POST.get('valid_from') or str(today)
            valid_to = request.POST.get('valid_to') or str(today + timedelta(days=30))
            usage_limit = int(request.POST.get('usage_limit', 100))

            if not code:
                messages.error(request, "Coupon code is required.")
                return redirect('/admin/pricing/')

            if CouponDiscount.objects.filter(code=code).exists():
                messages.error(request, f"Coupon code '{code}' already exists.")
                return redirect('/admin/pricing/')

            coupon = CouponDiscount.objects.create(
                code=code,
                description=description,
                discount_type=discount_type,
                discount_value=discount_value,
                min_amount=min_amount,
                max_discount=max_discount,
                valid_from=valid_from,
                valid_to=valid_to,
                usage_limit=usage_limit,
                active=True
            )
            record_admin_activity(request, 'coupon_created', coupon, {'code': code, 'discount_value': str(discount_value)})
            messages.success(request, f"Coupon '{code}' created successfully.")
            return redirect('/admin/pricing/')

        elif action == 'toggle_coupon':
            coupon_id = request.POST.get('coupon_id')
            coupon = get_object_or_404(CouponDiscount, id=coupon_id)
            coupon.active = not coupon.active
            coupon.save(update_fields=['active'])
            messages.success(request, f"Coupon '{coupon.code}' is now {'Active' if coupon.active else 'Disabled'}.")
            return redirect('/admin/pricing/')

        elif action == 'delete_coupon':
            coupon_id = request.POST.get('coupon_id')
            coupon = get_object_or_404(CouponDiscount, id=coupon_id)
            c_code = coupon.code
            coupon.delete()
            messages.success(request, f"Coupon '{c_code}' deleted.")
            return redirect('/admin/pricing/')

    plans = PricingPlan.objects.select_related('movie', 'created_by').order_by('-start_date')
    coupons = CouponDiscount.objects.all().order_by('-created_at')
    history = PricingHistory.objects.select_related('plan', 'theater', 'changed_by').order_by('-created_at')[:25]

    all_movies = Movie.objects.filter(status='CURRENT').order_by('name')
    if not all_movies.exists():
        all_movies = Movie.objects.all().order_by('name')[:30]

    all_theatres = CinemaVenue.objects.filter(active=True).order_by('name')

    context = {
        'plans': plans,
        'coupons': coupons,
        'history': history,
        'all_movies': all_movies,
        'all_theatres': all_theatres,
        'screen_types': Screen.SCREEN_TYPES,
        'today': today,
        'title': 'Weekly & Date-Based Ticket Pricing',
    }
    return render(request, 'admin/pricing_list.html', context)

