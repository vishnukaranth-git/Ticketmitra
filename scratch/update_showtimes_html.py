with open('Ticketmitra/templates/admin/showtimes_list.html', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Update top buttons
top_btns_target = """    <div class="d-flex" style="gap: 10px;">
      <button type="button" class="tm-btn tm-btn-primary" onclick="openCreateShowtimeModal()">
        <i class="fas fa-plus mr-1"></i> + Create Showtime
      </button>
    </div>"""

top_btns_replacement = """    <div class="d-flex flex-wrap" style="gap: 10px;">
      <button type="button" class="tm-btn tm-btn-primary" onclick="openCreateShowtimeModal()">
        <i class="fas fa-plus mr-1"></i> + Single Showtime
      </button>
      <button type="button" class="tm-btn tm-btn-secondary" onclick="openRecurringShowtimeModal()">
        <i class="fas fa-calendar-week mr-1"></i> + Generate Recurring
      </button>
    </div>"""

if top_btns_target in c:
    c = c.replace(top_btns_target, top_btns_replacement, 1)

# 2. Update filters bar to add View Mode toggle (List / Calendar)
filter_bar_target = """        <button type="submit" class="tm-btn tm-btn-primary py-2 px-3">
          <i class="fas fa-filter mr-1"></i> Filter
        </button>
        {% if selected_theatre or selected_movie_id or selected_date %}
          <a href="/admin/showtimes/" class="tm-btn tm-btn-ghost py-2 px-3">Reset</a>
        {% endif %}
      </form>"""

filter_bar_replacement = """        <button type="submit" class="tm-btn tm-btn-primary py-2 px-3">
          <i class="fas fa-filter mr-1"></i> Filter
        </button>
        {% if selected_theatre or selected_movie_id or selected_date %}
          <a href="/admin/showtimes/" class="tm-btn tm-btn-ghost py-2 px-3">Reset</a>
        {% endif %}

        <div class="ml-auto d-flex align-items-center" style="gap: 6px;">
          <a href="?view=list{% if selected_theatre %}&theatre={{ selected_theatre }}{% endif %}{% if selected_movie_id %}&movie_id={{ selected_movie_id }}{% endif %}{% if selected_date %}&date={{ selected_date }}{% endif %}" class="tm-btn-sm {% if view_mode != 'calendar' %}tm-btn-primary{% else %}tm-btn-ghost{% endif %}">
            <i class="fas fa-list mr-1"></i> List View
          </a>
          <a href="?view=calendar{% if selected_theatre %}&theatre={{ selected_theatre }}{% endif %}{% if selected_movie_id %}&movie_id={{ selected_movie_id }}{% endif %}{% if selected_date %}&date={{ selected_date }}{% endif %}" class="tm-btn-sm {% if view_mode == 'calendar' %}tm-btn-primary{% else %}tm-btn-ghost{% endif %}">
            <i class="fas fa-calendar-alt mr-1"></i> Weekly Calendar
          </a>
        </div>
      </form>"""

if filter_bar_target in c:
    c = c.replace(filter_bar_target, filter_bar_replacement, 1)

# 3. Add calendar view rendering right above SHOWTIMES TABLE
table_target = """  <!-- SHOWTIMES TABLE -->
  <div class="tm-panel-card">"""

calendar_and_table = """  {% if view_mode == 'calendar' %}
    <!-- WEEKLY CALENDAR VIEW -->
    <div class="tm-panel-card mb-4">
      <div class="tm-panel-header">
        <div class="tm-panel-title">
          <i class="fas fa-calendar-alt text-info"></i>
          <span>Weekly Schedule Grid &bull; Week of {{ ref_date|date:"M d, Y" }}</span>
        </div>
        <div class="d-flex align-items-center" style="gap: 8px;">
          <span class="badge badge-success" style="font-size: 11px;">Conflict Protected</span>
          <span class="badge badge-info" style="font-size: 11px;">Turnaround Buffered</span>
        </div>
      </div>
      <div class="tm-panel-body p-3">
        <div class="row">
          {% for day in calendar_days %}
            <div class="col" style="min-width: 155px; border-right: 1px solid rgba(255,255,255,0.06); padding: 6px;">
              <div class="text-center p-2 rounded mb-2 {% if day == today %}bg-primary text-white{% else %}bg-dark text-muted{% endif %}" style="font-size: 12px; font-weight: bold;">
                <div>{{ day|date:"D" }}</div>
                <div style="font-size: 14px;">{{ day|date:"M d" }}</div>
              </div>
              <div style="display: flex; flex-direction: column; gap: 8px;">
                {% for show_key, shows in calendar_data.items %}
                  {% if show_key == day|date:'Y-m-d' %}
                    {% for s in shows %}
                      <div class="p-2 rounded" style="background: rgba(20, 26, 41, 0.95); border: 1px solid rgba(255,255,255,0.08); font-size: 11px;">
                        <div class="d-flex justify-content-between align-items-center mb-1">
                          <strong class="text-info">{{ s.time|date:"h:i A" }}</strong>
                          <span class="badge badge-secondary" style="font-size: 9px;">{{ s.screen.screen_type|default:"2D" }}</span>
                        </div>
                        <div class="font-weight-bold text-white text-truncate" title="{{ s.movie.get_display_title }}">
                          {{ s.movie.get_display_title }}
                        </div>
                        <div class="text-muted text-truncate" style="font-size: 10px;">
                          {{ s.screen.name|default:"Main" }} &bull; ₹{{ s.price|floatformat:0 }}
                        </div>
                        <div class="mt-1 d-flex justify-content-between align-items-center">
                          <a href="/admin/seats/?theater_id={{ s.id }}" class="text-success font-weight-bold" style="font-size: 10px;">
                            <i class="fas fa-chair"></i> Seats
                          </a>
                          <span class="text-muted" style="font-size: 9px;">{{ s.language|upper|default:"EN" }}</span>
                        </div>
                      </div>
                    {% empty %}
                      <div class="text-center text-muted py-3" style="font-size: 11px;">No Shows</div>
                    {% endfor %}
                  {% endif %}
                {% endfor %}
              </div>
            </div>
          {% endfor %}
        </div>
      </div>
    </div>
  {% else %}
  <!-- SHOWTIMES TABLE -->
  <div class="tm-panel-card">"""

if table_target in c:
    c = c.replace(table_target, calendar_and_table, 1)

# Close the {% else %} condition before the modal
modal_target = """<!-- CREATE SHOWTIME MODAL -->"""
modal_code = """{% endif %}

<!-- RECURRING SHOWTIME GENERATOR MODAL -->
<div id="recurringShowtimeModal" style="display: none; position: fixed; inset: 0; z-index: 9999; background: rgba(0,0,0,0.8); backdrop-filter: blur(4px); align-items: center; justify-content: center; padding: 20px;">
  <div style="background: #111827; border: 1px solid var(--tm-border); border-radius: 12px; width: 100%; max-width: 640px; max-height: 90vh; overflow-y: auto; padding: 25px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h4 class="text-white font-weight-bold mb-0"><i class="fas fa-calendar-week text-danger mr-2"></i> + Generate Recurring Showtimes</h4>
      <button type="button" class="btn text-white p-0" onclick="closeRecurringShowtimeModal()" style="font-size: 20px;">&times;</button>
    </div>
    <form method="POST" action="/admin/showtimes/">
      {% csrf_token %}
      <input type="hidden" name="action" value="generate_recurring_showtimes">

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Select Movie *</label>
        <select name="movie_id" required class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
          {% for m in all_movies %}
            <option value="{{ m.id }}">{{ m.get_display_title }} ({{ m.original_language|upper }})</option>
          {% endfor %}
        </select>
      </div>

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Select Theatre Complex *</label>
        <select name="theater_name" id="modalRecurTheatreSelect" required class="form-control" onchange="filterScreensByTheatre(this.value, 'modalRecurScreenSelect')" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
          {% for th in all_theatres %}
            <option value="{{ th.name }}">{{ th.name }} ({{ th.city }})</option>
          {% endfor %}
        </select>
      </div>

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Select Screen / Auditorium *</label>
        <select name="screen_id" id="modalRecurScreenSelect" required class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
          {% for sc in all_screens %}
            <option value="{{ sc.id }}" data-theatre="{{ sc.theater_name }}">{{ sc.theater_name }} &bull; {{ sc.name }} ({{ sc.screen_type }})</option>
          {% endfor %}
        </select>
      </div>

      <div class="row">
        <div class="col-md-6 form-group mb-3">
          <label class="text-muted small font-weight-bold">Start Date *</label>
          <input type="date" name="start_date" required class="form-control" id="modalRecurStartDate" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
        </div>
        <div class="col-md-6 form-group mb-3">
          <label class="text-muted small font-weight-bold">End Date *</label>
          <input type="date" name="end_date" required class="form-control" id="modalRecurEndDate" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
        </div>
      </div>

      <div class="form-group mb-3">
        <label class="text-muted small font-weight-bold">Daily Showtime Slots (Comma separated) *</label>
        <input type="text" name="time_slots" value="10:30, 14:15, 18:00, 21:30" required class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
        <small class="text-muted">Example: 10:30, 14:15, 18:00, 21:30 (24-hour HH:MM format)</small>
      </div>

      <div class="row">
        <div class="col-md-6 form-group mb-3">
          <label class="text-muted small font-weight-bold">Language</label>
          <input type="text" name="language" placeholder="e.g. Kannada, Hindi, English" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
        </div>
        <div class="col-md-6 form-group mb-3">
          <label class="text-muted small font-weight-bold">Base Price Override (₹, optional)</label>
          <input type="number" step="10" name="base_price" placeholder="Auto-resolved from Pricing Plan" class="form-control" style="background: #141A29; color: #fff; border: 1px solid var(--tm-border); border-radius: 8px;">
        </div>
      </div>

      <div class="form-check mb-4">
        <input type="checkbox" class="form-check-input" name="subtitles_available" id="recurSubs">
        <label class="form-check-label text-muted small" for="recurSubs">English Subtitles Available</label>
      </div>

      <div class="d-flex justify-content-end" style="gap: 10px;">
        <button type="button" class="tm-btn tm-btn-ghost" onclick="closeRecurringShowtimeModal()">Cancel</button>
        <button type="submit" class="tm-btn tm-btn-primary"><i class="fas fa-magic mr-1"></i> Generate All Recurring Showtimes</button>
      </div>
    </form>
  </div>
</div>

<!-- CREATE SHOWTIME MODAL -->"""

if modal_target in c:
    c = c.replace(modal_target, modal_code, 1)

# Add helper js
js_helper = """
function openRecurringShowtimeModal() {
  const today = new Date().toISOString().split('T')[0];
  const nextWeek = new Date(Date.now() + 7 * 86400000).toISOString().split('T')[0];
  document.getElementById('modalRecurStartDate').value = today;
  document.getElementById('modalRecurEndDate').value = nextWeek;
  const thSelect = document.getElementById('modalRecurTheatreSelect');
  if (thSelect) filterScreensByTheatre(thSelect.value, 'modalRecurScreenSelect');
  document.getElementById('recurringShowtimeModal').style.display = 'flex';
}
function closeRecurringShowtimeModal() {
  document.getElementById('recurringShowtimeModal').style.display = 'none';
}
"""

c = c.replace("function openCreateShowtimeModal() {", js_helper + "\nfunction openCreateShowtimeModal() {", 1)

with open('Ticketmitra/templates/admin/showtimes_list.html', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated showtimes_list.html successfully")

