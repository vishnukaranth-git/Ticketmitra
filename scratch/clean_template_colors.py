import os

replacements = {
    '#070B14': 'rgba(11, 25, 43, 0.85)',
    '#0D1220': '#0B192B',
    '#141A29': 'rgba(27, 41, 64, 0.72)',
    '#1B2233': 'rgba(27, 41, 64, 0.85)',
    '#E63946': 'var(--tm-crimson)',
}

files_to_check = [
    'movies_list.html',
    'payments_list.html',
    'pricing_list.html',
    'screens_list.html',
    'showtimes_list.html',
    'theatres_list.html',
    'visual_seat_map.html',
    'login.html',
    'analytics.html'
]

for fn in files_to_check:
    path = os.path.join('Ticketmitra/templates/admin', fn)
    if not os.path.exists(path):
        continue
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    modified = False
    for old, new in replacements.items():
        if old in content:
            content = content.replace(old, new)
            modified = True
            print(f'Replaced {old} -> {new} in {fn}')

    if fn == 'visual_seat_map.html' and 'background: #3B82F6;' in content:
        content = content.replace('background: #3B82F6;', 'background: var(--tm-crimson);')
        modified = True
        print('Updated selected seat color in visual_seat_map.html')

    if fn == 'analytics.html' and "'Inter', sans-serif" in content:
        content = content.replace("'Inter', sans-serif", "'DM Sans', sans-serif")
        modified = True
        print('Updated chart font in analytics.html')

    if modified:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Successfully updated {fn}')

