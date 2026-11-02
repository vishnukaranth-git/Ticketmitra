with open('Ticketmitra/movies/urls.py', 'r', encoding='utf-8') as f:
    c = f.read()

target = "path('checkout/<int:reservation_id>/', views.checkout, name='checkout'),"
replacement = "path('checkout/<int:reservation_id>/', views.checkout, name='checkout'),\n    path('checkout/<int:reservation_id>/apply-coupon/', views.apply_coupon, name='apply_coupon'),"

if target in c:
    c = c.replace(target, replacement, 1)
    with open('Ticketmitra/movies/urls.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Updated movies/urls.py successfully")
else:
    print("Target not found in movies/urls.py")

