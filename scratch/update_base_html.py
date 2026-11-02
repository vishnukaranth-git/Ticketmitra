with open('Ticketmitra/templates/admin/base.html', 'r', encoding='utf-8') as f:
    c = f.read()

target = """        <a href="/admin/seats/" class="tm-nav-item {% if '/admin/seats/' in request.path or '/admin/operations/manage-seats/' in request.path %}active{% endif %}">
          <i class="fas fa-chair"></i>
          <span>Seat Layout</span>
        </a>"""

replacement = """        <a href="/admin/seats/" class="tm-nav-item {% if '/admin/seats/' in request.path or '/admin/operations/manage-seats/' in request.path %}active{% endif %}">
          <i class="fas fa-chair"></i>
          <span>Seat Layout</span>
        </a>
        <a href="/admin/pricing/" class="tm-nav-item {% if '/admin/pricing/' in request.path %}active{% endif %}">
          <i class="fas fa-tags"></i>
          <span>Ticket Pricing</span>
        </a>"""

if target in c:
    c = c.replace(target, replacement, 1)
    with open('Ticketmitra/templates/admin/base.html', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Updated base.html successfully")
else:
    print("Target not found in base.html")

