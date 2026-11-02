import os

path = r'Ticketmitra\templates\admin\showtimes_list.html'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

# Row update
old_row = """                  <!-- Time & Date -->
                  <td style="padding: 12px 18px; vertical-align: middle;">
                    <div class="font-weight-bold text-white mb-0" style="font-size: 14.5px;">
                      <i class="far fa-clock text-info mr-1"></i> {{ s.time|date:"h:i A" }}
                    </div>
                    <div class="text-muted small">
                      {{ s.time|date:"D, M d, Y" }}
                    </div>
                  </td>"""

new_row = """                  <!-- Time & Date -->
                  <td style="padding: 12px 18px; vertical-align: middle;">
                    <div class="font-weight-bold text-white mb-0" style="font-size: 14.5px;">
                      <i class="far fa-clock text-info mr-1"></i> {{ s.time|date:"h:i A" }} &ndash; {{ s.end_time|date:"h:i A" }}
                    </div>
                    <div class="text-muted small">
                      {{ s.time|date:"D, M d, Y" }} &bull; +{{ s.screen.turnaround_minutes|default:30 }}m clean
                    </div>
                  </td>"""

c = c.replace(old_row, new_row)
c = c.replace(old_row.replace('\r\n', '\n'), new_row)

old_format = """                  <!-- Format Badge -->
                  <td style="padding: 12px 18px; vertical-align: middle; text-align: center;">
                    {% if s.screen and s.screen.screen_type == 'IMAX' %}
                      <span class="tm-badge tm-badge-blue">IMAX</span>
                    {% elif s.screen and s.screen.screen_type == '4DX' %}
                      <span class="tm-badge tm-badge-red">4DX</span>
                    {% elif s.screen and s.screen.screen_type == 'PXL' %}
                      <span class="tm-badge tm-badge-purple">PXL</span>
                    {% elif s.screen and s.screen.screen_type == 'Gold' %}
                      <span class="tm-badge tm-badge-orange">GOLD</span>
                    {% else %}
                      <span class="tm-badge tm-badge-gray">{{ s.screen.screen_type|default:"2D" }}</span>
                    {% endif %}
                  </td>"""

new_format = """                  <!-- Format & Status Badge -->
                  <td style="padding: 12px 18px; vertical-align: middle; text-align: center;">
                    <div class="d-flex flex-column align-items-center" style="gap: 4px;">
                      <div>
                        {% if s.screen and s.screen.screen_type == 'IMAX' %}
                          <span class="tm-badge tm-badge-blue">IMAX</span>
                        {% elif s.screen and s.screen.screen_type == '4DX' %}
                          <span class="tm-badge tm-badge-red">4DX</span>
                        {% elif s.screen and s.screen.screen_type == 'PXL' %}
                          <span class="tm-badge tm-badge-purple">PXL</span>
                        {% elif s.screen and s.screen.screen_type == 'Gold' %}
                          <span class="tm-badge tm-badge-orange">GOLD</span>
                        {% else %}
                          <span class="tm-badge tm-badge-gray">{{ s.screen.screen_type|default:"2D" }}</span>
                        {% endif %}
                      </div>
                      <div>
                        {% if s.operational_status == 'BOOKING_OPEN' %}
                          <span class="tm-badge tm-badge-green" style="font-size: 10px;">PUBLISHED</span>
                        {% elif s.operational_status == 'SCHEDULED' %}
                          <span class="tm-badge tm-badge-blue" style="font-size: 10px;">SCHEDULED</span>
                        {% elif s.operational_status == 'DRAFT' %}
                          <span class="tm-badge tm-badge-gray" style="font-size: 10px;">DRAFT</span>
                        {% elif s.operational_status == 'CANCELLED' %}
                          <span class="tm-badge tm-badge-red" style="font-size: 10px;">CANCELLED</span>
                        {% else %}
                          <span class="tm-badge tm-badge-purple" style="font-size: 10px;">{{ s.operational_status }}</span>
                        {% endif %}
                      </div>
                    </div>
                  </td>"""

c = c.replace(old_format, new_format)
c = c.replace(old_format.replace('\r\n', '\n'), new_format)

old_actions = """                      <a href="/admin/seats/?theater_id={{ s.id }}" class="tm-btn tm-btn-primary py-1 px-2 small" title="Manage Seats for this show">
                        <i class="fas fa-chair mr-1"></i> Seats
                      </a>
                      <form method="POST" action="/admin/showtimes/" onsubmit="return confirm('Cancel this showtime? Existing bookings will remain in the audit history.');" style="margin: 0; display: inline;">"""

new_actions = """                      <a href="/admin/seats/?theater_id={{ s.id }}" class="tm-btn tm-btn-primary py-1 px-2 small" title="Manage Seats for this show">
                        <i class="fas fa-chair mr-1"></i> Seats
                      </a>
                      <button type="button" class="tm-btn tm-btn-ghost py-1 px-2 small" onclick="openEditShowtimeModal('{{ s.id }}', '{{ s.operational_status }}', '{{ s.price }}', '{{ s.language|default:''|escapejs }}', {{ s.subtitles_available|yesno:'true,false' }})" title="Edit Showtime">
                        <i class="fas fa-edit"></i>
                      </button>
                      <form method="POST" action="/admin/showtimes/" onsubmit="return confirm('Cancel this showtime? Existing bookings will remain in the audit history.');" style="margin: 0; display: inline;">"""

c = c.replace(old_actions, new_actions)
c = c.replace(old_actions.replace('\r\n', '\n'), new_actions)

# In Create Showtime modal, add Operational Status & Pricing Plan select
old_create_inputs = """      <div class="form-group mb-4">
        <label class="text-muted small font-weight-bold">Ticket Price (₹ INR) *</label>
        <input type="number" step="10" name="price" value="250" required class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
      </div>"""

new_create_inputs = """      <div class="row">
        <div class="col-md-6 form-group mb-3">
          <label class="text-muted small font-weight-bold">Operational Status *</label>
          <select name="operational_status" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
            <option value="BOOKING_OPEN" selected>Published / Open (Customer Visible)</option>
            <option value="SCHEDULED">Scheduled (Active)</option>
            <option value="DRAFT">Draft (Hidden from Customers)</option>
          </select>
        </div>
        <div class="col-md-6 form-group mb-3">
          <label class="text-muted small font-weight-bold">Pricing Plan (Optional)</label>
          <select name="pricing_plan_id" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
            <option value="">Manual / Custom Pricing</option>
            {% for plan in all_pricing_plans %}
              <option value="{{ plan.id }}">{{ plan.name }} (₹{{ plan.base_price }})</option>
            {% endfor %}
          </select>
        </div>
      </div>

      <div class="form-group mb-4">
        <label class="text-muted small font-weight-bold">Ticket Base Price (₹ INR) *</label>
        <input type="number" step="10" name="price" value="250" required class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
      </div>"""

c = c.replace(old_create_inputs, new_create_inputs)
c = c.replace(old_create_inputs.replace('\r\n', '\n'), new_create_inputs)

# Add EDIT SHOWTIME MODAL before script
edit_modal = """
<!-- EDIT SHOWTIME MODAL -->
<div id="editShowtimeModal" style="display: none; position: fixed; inset: 0; z-index: 9999; background: rgba(0,0,0,0.8); backdrop-filter: blur(4px); align-items: center; justify-content: center; padding: 20px;">
  <div style="background: #111827; border: 1px solid var(--tm-border); border-radius: 12px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; padding: 25px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h4 class="text-white font-weight-bold mb-0"><i class="fas fa-edit text-warning mr-2"></i> Edit Showtime</h4>
      <button type="button" class="btn text-white p-0" onclick="closeEditShowtimeModal()" style="font-size: 20px;">&times;</button>
    </div>
    <form method="POST" action="/admin/showtimes/">
      {% csrf_token %}
      <input type="hidden" name="action" value="edit_showtime">
      <input type="hidden" name="showtime_id" id="editShowtimeId">

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Operational Status</label>
        <select name="operational_status" id="editOperationalStatus" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
          <option value="BOOKING_OPEN">Published / Open (Visible on website)</option>
          <option value="SCHEDULED">Scheduled</option>
          <option value="DRAFT">Draft (Hidden from customers)</option>
          <option value="CANCELLED">Cancelled</option>
          <option value="COMPLETED">Completed</option>
        </select>
      </div>

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Base Ticket Price (₹ INR)</label>
        <input type="number" step="10" name="price" id="editPrice" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
      </div>

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Language Audio Track</label>
        <input type="text" name="language" id="editLanguage" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
      </div>

      <div class="form-check mb-4">
        <input type="checkbox" class="form-check-input" name="subtitles_available" id="editSubtitles">
        <label class="form-check-label text-muted small" for="editSubtitles">English Subtitles Available</label>
      </div>

      <div class="d-flex justify-content-end" style="gap: 10px;">
        <button type="button" class="tm-btn tm-btn-ghost" onclick="closeEditShowtimeModal()">Cancel</button>
        <button type="submit" class="tm-btn tm-btn-primary"><i class="fas fa-save mr-1"></i> Save Showtime</button>
      </div>
    </form>
  </div>
</div>
"""

script_addition = """
function openEditShowtimeModal(id, status, price, language, subs) {
  document.getElementById('editShowtimeId').value = id;
  document.getElementById('editOperationalStatus').value = status;
  document.getElementById('editPrice').value = price;
  document.getElementById('editLanguage').value = language;
  document.getElementById('editSubtitles').checked = Boolean(subs);
  document.getElementById('editShowtimeModal').style.display = 'flex';
}
function closeEditShowtimeModal() {
  document.getElementById('editShowtimeModal').style.display = 'none';
}
"""

if 'editShowtimeModal' not in c:
    c = c.replace('<!-- CREATE SHOWTIME MODAL -->', edit_modal + '\n<!-- CREATE SHOWTIME MODAL -->')
    c = c.replace('</script>', script_addition + '\n</script>')

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)

print("showtimes_list.html completely updated!")

