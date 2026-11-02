with open('Ticketmitra/Ticketmitra/urls.py', 'r', encoding='utf-8') as f:
    c = f.read()
target = "path('admin/seats/', admin_views.visual_seat_map_view, name='admin_seats'),"
replacement = "path('admin/seats/', admin_views.visual_seat_map_view, name='admin_seats'),\n    path('admin/pricing/', admin_views.admin_pricing_view, name='admin_pricing'),"
if target in c:
    c = c.replace(target, replacement, 1)
    with open('Ticketmitra/Ticketmitra/urls.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Updated urls.py successfully")
else:
    print("Target not found in urls.py")

