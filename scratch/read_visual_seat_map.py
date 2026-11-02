with open('Ticketmitra/templates/admin/visual_seat_map.html', 'r', encoding='utf-8') as f:
    text = f.read()
print('Length:', len(text))
print(text[:1000])
print('--- SCRIPT PART ---')
script_idx = text.find('<script>')
print(text[script_idx:script_idx+1200])

