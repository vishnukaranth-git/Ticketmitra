with open('Ticketmitra/movies/admin_views.py', 'r', encoding='utf-8') as f:
    text = f.read()
target = 'def admin_bookings_view'
idx = text.find(target)
if idx != -1:
    print(text[idx:idx+1500])

