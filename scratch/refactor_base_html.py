with open('Ticketmitra/templates/admin/base.html', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Remove Prominent Admin Test 'BOOK NOW' Button and replace with "Live Customer Site"
book_now_target = """        <!-- Prominent Admin Test 'BOOK NOW' Button -->
        <a href="{% url 'admin_quick_booking' %}" class="tm-btn-book-now" title="Test Live Ticket Booking Flow">
          <i class="fas fa-ticket-alt"></i>
          <span>BOOK NOW</span>
        </a>"""

site_link_replacement = """        <!-- View Customer-Facing Website -->
        <a href="{% url 'home' %}" target="_blank" class="tm-btn-sm tm-btn-ghost text-light d-none d-sm-flex align-items-center" title="Open Customer Website in New Tab" style="gap: 6px; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--tm-border);">
          <i class="fas fa-external-link-alt text-muted" style="font-size: 11px;"></i>
          <span style="font-size: 12px; font-weight: 500;">Customer Site</span>
        </a>"""

if book_now_target in c:
    c = c.replace(book_now_target, site_link_replacement, 1)

# 2. Add scroll preservation script before </body>
script_target = "</body>"
script_code = """<script>
// Prevent sidebar scrolling jumping on navigation
(function() {
  const sidebar = document.getElementById('tmSidebar');
  if (sidebar) {
    const saved = sessionStorage.getItem('tm_sidebar_scroll');
    if (saved !== null) {
      sidebar.scrollTop = parseInt(saved, 10);
    }
    sidebar.addEventListener('scroll', function() {
      sessionStorage.setItem('tm_sidebar_scroll', sidebar.scrollTop);
    }, { passive: true });
    window.addEventListener('beforeunload', function() {
      sessionStorage.setItem('tm_sidebar_scroll', sidebar.scrollTop);
    });
  }
})();
</script>
</body>"""

if script_target in c:
    c = c.replace(script_target, script_code, 1)

with open('Ticketmitra/templates/admin/base.html', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated base.html successfully")

