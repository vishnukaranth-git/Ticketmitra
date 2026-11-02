import os, re
classes = set()
for root, dirs, files in os.walk('Ticketmitra/templates/admin'):
    for f in files:
        if f.endswith('.html'):
            with open(os.path.join(root, f), 'r', encoding='utf-8') as fl:
                matches = re.findall(r'class=["\']([^"\']+)["\']', fl.read())
                for m in matches:
                    for cls in m.split():
                        if cls.startswith('tm-'):
                            classes.add(cls)
print(f'Total .tm- classes in admin templates: {len(classes)}')
for c in sorted(classes):
    print(c)

