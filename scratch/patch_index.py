import os

path = r'Ticketmitra\templates\admin\index.html'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

old_form = """  <form method="get" class="tm-panel-card mb-4" style="padding:16px;display:flex;gap:12px;flex-wrap:wrap;align-items:end">
    <label>Date from <input type="date" name="date_from" value="{{ date_from }}"></label>
    <label>Date to <input type="date" name="date_to" value="{{ date_to }}"></label>
    <label>Theatre <select name="theatre"><option value="">All theatres</option>{% for item in theatre_options %}<option value="{{ item.id }}" {% if selected_theatre == item.id|stringformat:'s' %}selected{% endif %}>{{ item.name }}</option>{% endfor %}</select></label>
    <label>Movie <select name="movie"><option value="">All movies</option>{% for item in movie_options %}<option value="{{ item.id }}" {% if selected_movie == item.id|stringformat:'s' %}selected{% endif %}>{{ item.get_display_title }}</option>{% endfor %}</select></label>
    <label>Booking status <select name="status"><option value="">All statuses</option><option value="CONFIRMED" {% if selected_status == 'CONFIRMED' %}selected{% endif %}>Confirmed</option><option value="CANCELLED" {% if selected_status == 'CANCELLED' %}selected{% endif %}>Cancelled</option></select></label>
    <button class="tm-btn tm-btn-primary" type="submit">Apply filters</button>
    <a class="tm-btn tm-btn-ghost" href="/admin/dashboard/">Reset</a>
  </form>"""

new_form = """  <!-- OPERATIONAL FILTERS -->
  <div class="tm-panel-card mb-4">
    <div class="tm-panel-body p-3">
      <form method="get" class="d-flex align-items-end flex-wrap" style="gap: 12px;">
        <div style="min-width: 140px;">
          <label class="text-muted small font-weight-bold mb-1">Date From</label>
          <input type="date" name="date_from" value="{{ date_from }}" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; font-size: 13px;">
        </div>
        <div style="min-width: 140px;">
          <label class="text-muted small font-weight-bold mb-1">Date To</label>
          <input type="date" name="date_to" value="{{ date_to }}" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; font-size: 13px;">
        </div>
        <div style="min-width: 170px;">
          <label class="text-muted small font-weight-bold mb-1">Theatre</label>
          <select name="theatre" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; font-size: 13px;">
            <option value="">All Theatres</option>
            {% for item in theatre_options %}
              <option value="{{ item.id }}" {% if selected_theatre == item.id|stringformat:'s' %}selected{% endif %}>{{ item.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div style="min-width: 170px;">
          <label class="text-muted small font-weight-bold mb-1">Movie</label>
          <select name="movie" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; font-size: 13px;">
            <option value="">All Movies</option>
            {% for item in movie_options %}
              <option value="{{ item.id }}" {% if selected_movie == item.id|stringformat:'s' %}selected{% endif %}>{{ item.get_display_title }}</option>
            {% endfor %}
          </select>
        </div>
        <div style="min-width: 140px;">
          <label class="text-muted small font-weight-bold mb-1">Booking Status</label>
          <select name="status" class="form-control" style="background: var(--tm-elevated); color: #fff; border: 1px solid var(--tm-border); border-radius: 8px; font-size: 13px;">
            <option value="">All Statuses</option>
            <option value="CONFIRMED" {% if selected_status == 'CONFIRMED' %}selected{% endif %}>Confirmed</option>
            <option value="CANCELLED" {% if selected_status == 'CANCELLED' %}selected{% endif %}>Cancelled</option>
          </select>
        </div>
        <div>
          <button class="tm-btn tm-btn-primary py-2 px-3" type="submit"><i class="fas fa-filter mr-1"></i> Filter</button>
          {% if date_from or date_to or selected_theatre or selected_movie or selected_status %}
            <a class="tm-btn tm-btn-ghost py-2 px-3 ml-2" href="/admin/dashboard/">Reset</a>
          {% endif %}
        </div>
      </form>
    </div>
  </div>"""

c = c.replace(old_form, new_form)
c = c.replace(old_form.replace('\r\n', '\n'), new_form)

old_metrics_strip = """  <div class="tm-metrics-grid">
    <div class="tm-metric-card"><div class="tm-metric-label">Gross verified revenue</div><div class="tm-metric-value">₹{{ gross_revenue|floatformat:2 }}</div></div>
    <div class="tm-metric-card"><div class="tm-metric-label">Refunds recorded</div><div class="tm-metric-value">₹{{ refunds|floatformat:2 }}</div></div>
    <div class="tm-metric-card"><div class="tm-metric-label">Theatre occupancy</div><div class="tm-metric-value">{{ occupancy }}%</div></div>
    <div class="tm-metric-card"><div class="tm-metric-label">Pending / failed payments</div><div class="tm-metric-value">{{ pending_payments }} / {{ failed_payments }}</div></div>
  </div>"""

new_metrics_strip = """  <!-- REVENUE & OPERATIONAL METRICS -->
  <div class="tm-metrics-grid mb-4">
    <div class="tm-metric-card">
      <div class="tm-metric-top">
        <div class="tm-metric-label">Gross Verified Revenue</div>
        <div class="tm-metric-icon-box green"><i class="fas fa-rupee-sign"></i></div>
      </div>
      <div class="tm-metric-value text-success">₹{{ gross_revenue|floatformat:2 }}</div>
      <div class="tm-metric-subtext positive"><i class="fas fa-shield-alt"></i> Stripe verified</div>
    </div>
    <div class="tm-metric-card">
      <div class="tm-metric-top">
        <div class="tm-metric-label">Refunds Processed</div>
        <div class="tm-metric-icon-box orange"><i class="fas fa-undo-alt"></i></div>
      </div>
      <div class="tm-metric-value text-warning">₹{{ refunds|floatformat:2 }}</div>
      <div class="tm-metric-subtext"><i class="fas fa-history"></i> Released & audited</div>
    </div>
    <div class="tm-metric-card">
      <div class="tm-metric-top">
        <div class="tm-metric-label">Theatre Occupancy</div>
        <div class="tm-metric-icon-box purple"><i class="fas fa-chart-pie"></i></div>
      </div>
      <div class="tm-metric-value">{{ occupancy }}%</div>
      <div class="tm-metric-subtext positive"><i class="fas fa-user-check"></i> Capacity utilized</div>
    </div>
    <div class="tm-metric-card">
      <div class="tm-metric-top">
        <div class="tm-metric-label">Active Holds & Unsettled</div>
        <div class="tm-metric-icon-box red"><i class="fas fa-hourglass-half"></i></div>
      </div>
      <div class="tm-metric-value">{{ active_holds|default:pending_payments }} <span style="font-size: 14px; color: var(--tm-text-muted); font-weight: normal;">holds</span></div>
      <div class="tm-metric-subtext"><i class="fas fa-clock"></i> 8-minute TTL</div>
    </div>
  </div>"""

c = c.replace(old_metrics_strip, new_metrics_strip)
c = c.replace(old_metrics_strip.replace('\r\n', '\n'), new_metrics_strip)

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)

print("index.html polished successfully!")

