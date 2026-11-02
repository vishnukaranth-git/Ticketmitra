import os

p1 = 'Ticketmitra/templates/admin/base.html'
with open(p1, 'r', encoding='utf-8') as f:
    c1 = f.read()

old_font = """  <!-- Google Fonts: DM Sans for admin UI -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&display=swap" rel="stylesheet">"""

new_font = """  <!-- Google Fonts: Playfair Display (display) + DM Sans (UI) -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;0,800;1,400;1,600;1,700&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&display=swap" rel="stylesheet">"""

if old_font in c1:
    c1 = c1.replace(old_font, new_font)
elif old_font.replace('\n', '\r\n') in c1:
    c1 = c1.replace(old_font.replace('\n', '\r\n'), new_font.replace('\n', '\r\n'))
else:
    print('old_font not found in base.html')

c1 = c1.replace('style="color: #E63946;"', 'style="color: var(--tm-crimson);"')

with open(p1, 'w', encoding='utf-8') as f:
    f.write(c1)
print('Successfully updated base.html')

p2 = 'Ticketmitra/templates/admin/base_site.html'
with open(p2, 'r', encoding='utf-8') as f:
    c2 = f.read()

old_site_font = """  <!-- Google Fonts: Outfit & Inter -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">"""

if old_site_font in c2:
    c2 = c2.replace(old_site_font, new_font)
elif old_site_font.replace('\n', '\r\n') in c2:
    c2 = c2.replace(old_site_font.replace('\n', '\r\n'), new_font.replace('\n', '\r\n'))
else:
    print('old_site_font not found in base_site.html')

with open(p2, 'w', encoding='utf-8') as f:
    f.write(c2)
print('Successfully updated base_site.html')

