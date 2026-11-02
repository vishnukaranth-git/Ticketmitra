with open('Ticketmitra/movies/admin_views.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Update visual_seat_map_view context
context_target = """    context = {
        'theater': theater,
        'screen': screen,
        'rows': sorted_rows,
        'total_seats': seats_qs.count(),
        'available_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'available'),
        'reserved_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'reserved'),
        'booked_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'booked'),
        'blocked_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'blocked'),
        'all_theaters': all_theaters,
        'all_screens': all_screens,
        'title': f"Manage Seats — {theater.name if theater else (screen.name if screen else 'All Screens')}",
    }"""

context_replacement = """    pricing_snapshot = theater.get_effective_pricing_snapshot() if theater else {
        'REGULAR': 180.0,
        'PREMIUM': 250.0,
        'RECLINER': 350.0,
        'VIP': 450.0,
        'ACCESSIBLE': 150.0,
    }

    context = {
        'theater': theater,
        'screen': screen,
        'rows': sorted_rows,
        'seats_json': json.dumps(sorted_rows),
        'pricing_json': json.dumps(pricing_snapshot),
        'total_seats': seats_qs.count(),
        'available_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'available'),
        'reserved_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'reserved'),
        'booked_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'booked'),
        'blocked_count': sum(1 for r in sorted_rows for s in r['seats'] if s['status'] == 'blocked'),
        'all_theaters': all_theaters,
        'all_screens': all_screens,
        'title': f"Manage Seats — {theater.name if theater else (screen.name if screen else 'All Screens')}",
    }"""

if context_target in c:
    c = c.replace(context_target, context_replacement, 1)

# 2. Add save_screen_layout in seat_action_api
clear_layout_target = """    elif action == 'clear_layout':
        theater_id = data.get('theater_id')
        theater = get_object_or_404(Theater, id=theater_id)
        booked_ids = set(Booking.objects.filter(theater=theater).values_list('seat_id', flat=True))
        deleted, _ = Seat.objects.filter(theater=theater).exclude(id__in=booked_ids).delete()
        return JsonResponse({'success': True, 'message': f"Cleared {deleted} unbooked seats."})"""

save_layout_code = """    elif action == 'save_screen_layout':
        screen_id = data.get('screen_id')
        theater_id = data.get('theater_id')
        rows_spec = data.get('rows_spec') or []

        screen = get_object_or_404(Screen, id=screen_id) if screen_id else None
        theater = get_object_or_404(Theater, id=theater_id) if theater_id else None
        if not screen and theater:
            screen = theater.screen

        if not screen:
            return JsonResponse({'success': False, 'error': 'Screen is required to save layout.'}, status=400)

        total_capacity = 0
        for r_item in rows_spec:
            total_capacity += int(r_item.get('cols', 8))

        layout_data = {
            'rows_spec': rows_spec,
            'aisle_columns': data.get('aisle_columns', [3, 7]),
            'updated_at': timezone.now().isoformat(),
        }
        screen.seating_layout = layout_data
        if total_capacity > 0:
            screen.capacity = total_capacity
        screen.save(update_fields=['seating_layout', 'capacity'])

        theaters_to_sync = [theater] if theater else list(Theater.objects.filter(screen=screen, active=True, time__gte=timezone.now()))
        created_count = 0
        for th in theaters_to_sync:
            booked_seat_names = set(Booking.objects.filter(theater=th).values_list('seat__seat_number', flat=True))
            for r_item in rows_spec:
                r_lbl = r_item.get('row', 'A').strip().upper()
                c_cnt = int(r_item.get('cols', 8))
                s_type = r_item.get('seat_type', 'REGULAR')
                acc_list = r_item.get('accessible', [])
                for col in range(1, c_cnt + 1):
                    seat_no = f"{r_lbl}{col}"
                    this_type = 'ACCESSIBLE' if col in acc_list else s_type
                    seat_obj, was_created = Seat.objects.get_or_create(
                        theater=th,
                        seat_number=seat_no,
                        defaults={
                            'screen': screen,
                            'row': r_lbl,
                            'seat_type': this_type,
                            'is_booked': False,
                            'is_blocked': False,
                        }
                    )
                    if was_created:
                        created_count += 1
                    elif seat_no not in booked_seat_names:
                        seat_obj.seat_type = this_type
                        seat_obj.save(update_fields=['seat_type'])

        record_admin_activity(request, 'screen_layout_saved', screen, {
            'screen': screen.name,
            'capacity': screen.capacity,
            'total_created': created_count
        })

        return JsonResponse({
            'success': True,
            'message': f"Saved 3D seating layout for screen {screen.name} ({screen.capacity} capacity). Created/synced {created_count} seat(s).",
            'capacity': screen.capacity
        })

    elif action == 'clear_layout':
        theater_id = data.get('theater_id')
        theater = get_object_or_404(Theater, id=theater_id)
        booked_ids = set(Booking.objects.filter(theater=theater).values_list('seat_id', flat=True))
        deleted, _ = Seat.objects.filter(theater=theater).exclude(id__in=booked_ids).delete()
        return JsonResponse({'success': True, 'message': f"Cleared {deleted} unbooked seats."})"""

if clear_layout_target in c:
    c = c.replace(clear_layout_target, save_layout_code, 1)

with open('Ticketmitra/movies/admin_views.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated admin_views.py for seat layout successfully")

