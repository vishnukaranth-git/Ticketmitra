import os

path = r'Ticketmitra\templates\admin\visual_seat_map.html'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Update Subtitle
old_sub = """      <p class="tm-hero-subtitle">
        {% if theater %}
          <strong>{{ theater.name }}</strong> ({{ theater.movie.get_display_title }}) &bull; {{ theater.screen.name|default:"Auditorium" }} &bull; {{ theater.time|date:"M d, Y - h:i A" }}
        {% elif screen %}
          <strong>{{ screen.theater_name }}</strong> &bull; {{ screen.name }} ({{ screen.screen_type }})
        {% else %}
          Select an auditorium or showtime to view and configure seats.
        {% endif %}
      </p>"""

new_sub = """      <p class="tm-hero-subtitle">
        {% if screen %}
          <span class="text-white font-weight-bold">{{ screen.theater_name }}</span> &bull; <span class="text-info font-weight-bold">{{ screen.name }}</span> ({{ screen.screen_type }}) &bull; <span class="text-success font-weight-bold">{{ total_seats }}</span> Seats Configured
        {% else %}
          Select an auditorium or screen to view and configure seats.
        {% endif %}
      </p>"""

c = c.replace(old_sub, new_sub)
c = c.replace(old_sub.replace('\r\n', '\n'), new_sub)

# 2. Remove Showtime Dropdown, keep Select Screen
old_dropdowns = """      <select class="form-control-sm" style="max-width: 240px; background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 6px;" onchange="if(this.value) window.location.href=this.value;">
        <option value="">-- Switch Showtime --</option>
        {% for th in all_theaters %}
          <option value="{% url 'admin_manage_seats_theater' th.id %}" {% if theater and theater.id == th.id %}selected{% endif %}>
            {{ th.name }} ({{ th.movie.name|truncatechars:18 }})
          </option>
        {% endfor %}
      </select>

      <select class="form-control-sm" style="max-width: 220px; background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 6px;" onchange="if(this.value) window.location.href=this.value;">
        <option value="">-- Switch Screen --</option>
        {% for sc in all_screens %}
          <option value="{% url 'admin_manage_seats_screen' sc.id %}" {% if screen and screen.id == sc.id %}selected{% endif %}>
            {{ sc.theater_name }} &bull; {{ sc.name }}
          </option>
        {% endfor %}
      </select>"""

new_dropdowns = """      <div class="d-flex align-items-center" style="gap: 8px;">
        <label class="text-muted small mb-0 font-weight-bold d-none d-sm-inline"><i class="fas fa-desktop text-info mr-1"></i> Screen:</label>
        <select class="form-control form-control-sm" style="min-width: 220px; max-width: 290px; background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 6px; font-weight: 600; padding: 4px 10px;" onchange="if(this.value) window.location.href=this.value;">
          <option value="">-- Select Screen --</option>
          {% for sc in all_screens %}
            <option value="{% url 'admin_manage_seats_screen' sc.id %}" {% if screen and screen.id == sc.id %}selected{% endif %}>
              {{ sc.theater_name }} &bull; {{ sc.name }} ({{ sc.screen_type }})
            </option>
          {% endfor %}
        </select>
      </div>"""

c = c.replace(old_dropdowns, new_dropdowns)
c = c.replace(old_dropdowns.replace('\r\n', '\n'), new_dropdowns)

# 3. JavaScript changes: remove THEATER_ID dependency and remove theater_id from JSON payloads
c = c.replace("const THEATER_ID = \"{{ theater.id|default:'' }}\";\n", "")
c = c.replace("const THEATER_ID = \"{{ theater.id|default:'' }}\";\r\n", "")

# In submitLayoutGenerator
c = c.replace("        theater_id: THEATER_ID,\n", "")
c = c.replace("        theater_id: THEATER_ID,\r\n", "")

# In submitAddRow
c = c.replace("        theater_id: THEATER_ID,\n", "")
c = c.replace("        theater_id: THEATER_ID,\r\n", "")

# In submitAddSeat
c = c.replace("        theater_id: THEATER_ID,\n", "")
c = c.replace("        theater_id: THEATER_ID,\r\n", "")

# In triggerGenerateSeats
c = c.replace("        theater_id: THEATER_ID,\n", "")
c = c.replace("        theater_id: THEATER_ID,\r\n", "")

# In triggerClearLayout
c = c.replace("        theater_id: THEATER_ID,\n", "")
c = c.replace("        theater_id: THEATER_ID,\r\n", "")

# Ensure redirect/reload after save layout goes to the screen url
c = c.replace("window.location.reload();", "window.location.href = '{% url 'admin_manage_seats_screen' screen.id %}';")

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)

print("visual_seat_map.html updated successfully!")

