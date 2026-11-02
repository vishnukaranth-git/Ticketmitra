with open('Ticketmitra/movies/admin_views.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Update showtime creation in admin_showtimes_view
target = """            category_prices.setdefault('REGULAR', str(base_price))
            category_prices.setdefault('PREMIUM', str(base_price))
            category_prices.setdefault('VIP', str(base_price))
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
                active=True
            )"""

replacement = """            # Check if pricing plan was chosen
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
            )"""

if target in c:
    c = c.replace(target, replacement, 1)

# 2. Add edit_showtime action
edit_target = "elif action == 'delete_showtime':"
edit_code = """elif action == 'edit_showtime':
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

        elif action == 'delete_showtime':"""

if edit_target in c:
    c = c.replace(edit_target, edit_code, 1)

# 3. Add status filter in admin_showtimes_view
filter_target = """    selected_movie_id = request.GET.get('movie_id')
    selected_theatre = request.GET.get('theatre', '').strip()
    selected_date = request.GET.get('date', '').strip()

    showtimes_qs = Theater.objects.select_related('movie', 'screen').order_by('-time')
    if selected_movie_id:
        showtimes_qs = showtimes_qs.filter(movie_id=selected_movie_id)
    if selected_theatre:
        showtimes_qs = showtimes_qs.filter(name=selected_theatre)
    if selected_date:
        showtimes_qs = showtimes_qs.filter(time__date=selected_date)"""

filter_replacement = """    selected_movie_id = request.GET.get('movie_id')
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
        showtimes_qs = showtimes_qs.filter(operational_status=selected_status)"""

if filter_target in c:
    c = c.replace(filter_target, filter_replacement, 1)

# 4. Add pricing plans to context in admin_showtimes_view
ctx_target = "'selected_date': selected_date,"
ctx_replacement = """'selected_date': selected_date,
        'selected_status': selected_status,
        'all_pricing_plans': PricingPlan.objects.filter(is_active=True).order_by('-start_date'),"""

if ctx_target in c:
    c = c.replace(ctx_target, ctx_replacement, 1)

with open('Ticketmitra/movies/admin_views.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated admin_showtimes_view with status, end time calculation, and edit action")

