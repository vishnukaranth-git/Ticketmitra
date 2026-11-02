import os

new_code = '''@staff_member_required
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
'''

path = r'Ticketmitra\movies\admin_views.py'
with open(path, 'r', encoding='utf-8') as f:
    orig = f.read()

# Replace from '@staff_member_required\ndef visual_seat_map_view(' to end of bulk_add_seats_view
start_marker = '@staff_member_required\ndef visual_seat_map_view(request, theater_id=None, screen_id=None):'
end_marker = "return render(request, 'admin/bulk_add_seats.html', {'screens': screens})"

start_idx = orig.find(start_marker)
assert start_idx != -1, "start_marker not found"

end_idx = orig.find(end_marker, start_idx)
assert end_idx != -1, "end_marker not found"
end_idx += len(end_marker)

updated = orig[:start_idx] + new_code + orig[end_idx:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(updated)

print("admin_views.py updated successfully!")

