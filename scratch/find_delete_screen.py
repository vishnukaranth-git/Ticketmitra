with open('Ticketmitra/movies/admin_views.py', 'r', encoding='utf-8') as f:
    text = f.read()
target = "action == 'delete_screen'"
idx = text.find(target)
if idx != -1:
    print(text[idx:idx+800])
else:
    print("Not found")

