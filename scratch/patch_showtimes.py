import os

path = r'Ticketmitra\templates\admin\showtimes_list.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add Status Filter
old_filter = """        <!-- Date Filter -->
        <div style="min-width: 160px;">
          <input type="date" name="date" value="{{ selected_date }}" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; padding: 8px 12px; font-size: 13.5px;">
        </div>

        <button type="submit" class="tm-btn tm-btn-primary py-2 px-3">
          <i class="fas fa-filter mr-1"></i> Filter
        </button>
        {% if selected_theatre or selected_movie_id or selected_date %}
          <a href="/admin/showtimes/" class="tm-btn tm-btn-ghost py-2 px-3">Reset</a>
        {% endif %}"""

new_filter = """        <!-- Date Filter -->
        <div style="min-width: 160px;">
          <input type="date" name="date" value="{{ selected_date }}" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; padding: 8px 12px; font-size: 13.5px;">
        </div>

        <!-- Operational Status Filter -->
        <div style="min-width: 170px;">
          <select name="status" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; padding: 8px 12px; font-size: 13.5px;">
            <option value="">All Statuses</option>
            <option value="BOOKING_OPEN" {% if selected_status == 'BOOKING_OPEN' %}selected{% endif %}>Published / Open</option>
            <option value="SCHEDULED" {% if selected_status == 'SCHEDULED' %}selected{% endif %}>Scheduled</option>
            <option value="DRAFT" {% if selected_status == 'DRAFT' %}selected{% endif %}>Draft</option>
            <option value="CANCELLED" {% if selected_status == 'CANCELLED' %}selected{% endif %}>Cancelled</option>
            <option value="COMPLETED" {% if selected_status == 'COMPLETED' %}selected{% endif %}>Completed</option>
          </select>
        </div>

        <button type="submit" class="tm-btn tm-btn-primary py-2 px-3">
          <i class="fas fa-filter mr-1"></i> Filter
        </button>
        {% if selected_theatre or selected_movie_id or selected_date or selected_status %}
          <a href="/admin/showtimes/" class="tm-btn tm-btn-ghost py-2 px-3">Reset</a>
        {% endif %}"""

# Normalise newlines for replacement
content = content.replace(old_filter.replace('\r\n', '\n'), new_filter)
content = content.replace(old_filter, new_filter)

# 2. Table columns & rows
old_table_head = """                <th style="padding: 14px 18px;">Showtime / Date</th>
                <th style="padding: 14px 18px;">Movie</th>
                <th style="padding: 14px 18px;">Theatre</th>
                <th style="padding: 14px 18px; text-align: center;">Auditorium / Screen</th>
                <th style="padding: 14px 18px; text-align: center;">Format</th>
                <th style="padding: 14px 18px; text-align: right;">Price</th>
                <th style="padding: 14px 18px; text-align: right;">Actions</th>"""

new_table_head = """                <th style="padding: 14px 18px;">Showtime & End Time</th>
                <th style="padding: 14px 18px;">Movie</th>
                <th style="padding: 14px 18px;">Theatre</th>
                <th style="padding: 14px 18px; text-align: center;">Auditorium / Screen</th>
                <th style="padding: 14px 18px; text-align: center;">Format & Status</th>
                <th style="padding: 14px 18px; text-align: right;">Price</th>
                <th style="padding: 14px 18px; text-align: right;">Actions</th>"""

content = content.replace(old_table_head.replace('\r\n', '\n'), new_table_head)
content = content.replace(old_table_head, new_table_head)

old_time_cell = """                  <!-- Time & Date -->
                  <td style="padding: 12px 18px; vertical-align: middle;">
                    <div class="font-weight-bold text-white mb-0" style="font-size: 14.5px;">
                       {{ s.time|date:"h:i A" }}
                    </div>
                    <div class="text-muted small">
                      {{ s.time|date:"D, M d, Y" }}
                    </div>
                  </td>"""

# Let's inspect the exact time cell text from file
print("Replacements done for filters & head.")
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated successfully.")

