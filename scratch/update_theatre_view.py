with open('Ticketmitra/movies/admin_views.py', 'r', encoding='utf-8') as f:
    c = f.read()

target_block = """            venue, created = CinemaVenue.objects.get_or_create(
                name=name,
                defaults={
                    'address': address,
                    'city': city,
                    'state': state,
                    'latitude': Decimal(lat) if lat else None,
                    'longitude': Decimal(lon) if lon else None,
                    'contact_number': contact,
                    'description': description,
                    'active': active,
                    'theatre_code': theatre_code,
                    'status': 'ACTIVE' if active else 'INACTIVE',
                    'pincode': request.POST.get('pincode', '').strip(),
                    'opens_at': request.POST.get('opens_at') or None,
                    'closes_at': request.POST.get('closes_at') or None,
                }
            )
            if not created:
                venue.address = address
                venue.city = city
                venue.state = state
                venue.active = active
                venue.status = 'ACTIVE' if active else 'INACTIVE'
                venue.theatre_code = theatre_code or venue.theatre_code
                venue.pincode = request.POST.get('pincode', venue.pincode).strip()
                venue.opens_at = request.POST.get('opens_at') or None
                venue.closes_at = request.POST.get('closes_at') or None
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
            venue.active = request.POST.get('active') == 'on'
            venue.status = 'ACTIVE' if venue.active else 'INACTIVE'
            venue.pincode = request.POST.get('pincode', venue.pincode).strip()
            venue.opens_at = request.POST.get('opens_at') or None
            venue.closes_at = request.POST.get('closes_at') or None
            venue.save()"""

replacement_block = """            status = request.POST.get('status', 'ACTIVE')
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
            venue.save()"""

if target_block in c:
    c = c.replace(target_block, replacement_block, 1)

# Add search filtering and stats in admin_theatres_view
query_target = """    venues = CinemaVenue.objects.all().order_by('name')
    theatres_data = []
    now = timezone.now()
    today = now.date()

    for v in venues:"""

query_replacement = """    q = request.GET.get('q', '').strip()
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

    for v in venues_qs:"""

if query_target in c:
    c = c.replace(query_target, query_replacement, 1)

with open('Ticketmitra/movies/admin_views.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated admin_theatres_view successfully")

