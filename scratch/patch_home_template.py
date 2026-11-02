import os

home_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'home.html')
with open(home_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add CSS for weekly-cycle-badge
css_target = """  .rail-control-btn:hover {
    background: var(--crimson, #D61F45);
    border-color: var(--crimson, #D61F45);
    color: #FFFFFF;
  }"""

css_replacement = """  .rail-control-btn:hover {
    background: var(--crimson, #D61F45);
    border-color: var(--crimson, #D61F45);
    color: #FFFFFF;
  }
  .weekly-cycle-badge {
    display: inline-flex;
    align-items: center;
    background: rgba(226, 211, 193, 0.08);
    border: 1px solid rgba(226, 211, 193, 0.2);
    color: var(--warm-ivory, #F2E9DC);
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 20px;
    letter-spacing: 0.03em;
    vertical-align: middle;
  }"""

# 2. Update the section header and rail
section_target_start = """  <section class="mb-5 pt-2" id="moviesSection">"""
section_target_end = """    </div>\n  </section>"""

# Find exact boundaries of moviesSection
start_idx = content.find(section_target_start)
if start_idx == -1:
    print("Could not find start of moviesSection!")
else:
    # Find the closing </section> of moviesSection
    end_tag = "</section>"
    end_idx = content.find(end_tag, start_idx)
    if end_idx == -1:
        print("Could not find end of moviesSection!")
    else:
        old_section = content[start_idx:end_idx + len(end_tag)]
        new_section = """  <section class="mb-5 pt-2" id="moviesSection">
    <div class="d-flex justify-content-between align-items-end section-editorial-header flex-wrap" style="gap: 12px;">
      <div>
        <div class="d-flex align-items-center flex-wrap" style="gap: 8px;">
          <div class="tracker-tag mb-0">
            <i class="fas fa-film"></i> NEW RELEASES & IN THEATRES
          </div>
          <span class="weekly-cycle-badge" id="weeklyCycleBadge" title="Automated Friday release cycle for Indian cinema">
            <i class="fas fa-calendar-check mr-1 text-warning"></i>
            <span id="weeklyCycleText">{{ friday_cycle_label|default:"Friday Release Cycle" }}</span>
          </span>
        </div>
        <h2 class="section-main-heading mt-1 mb-0">Movies</h2>
      </div>
      <div class="rail-controls-box d-flex align-items-center" style="gap: 8px;">
        <button class="rail-control-btn" id="refreshWeeklyMoviesBtn" type="button" title="Refresh latest weekly releases" aria-label="Refresh Movies">
          <i class="fas fa-sync-alt" id="refreshWeeklyIcon" style="font-size: 11px;"></i>
        </button>
        <button class="rail-control-btn" onclick="manualScroll('homepageMoviesRail', -360)" aria-label="Previous Movies">
          <i class="fas fa-chevron-left" style="font-size: 12px;"></i>
        </button>
        <button class="rail-control-btn" onclick="manualScroll('homepageMoviesRail', 360)" aria-label="Next Movies">
          <i class="fas fa-chevron-right" style="font-size: 12px;"></i>
        </button>
      </div>
    </div>

    <div id="homepageMoviesAlert" class="alert d-none my-2" style="background: rgba(21, 28, 48, 0.95); border: 1px solid rgba(214, 31, 69, 0.4); color: #F2E9DC; font-size: 13px; border-radius: 6px;">
      <i class="fas fa-info-circle text-warning mr-2"></i>
      <span id="homepageMoviesAlertMsg">Unable to refresh new releases from TMDB right now. Showing existing scheduled bookable showtimes.</span>
    </div>

    <div class="carousel-scroll-rail continuous-rail position-relative" id="homepageMoviesRail" data-auto-scroll="true" style="transition: opacity 0.25s ease;">
      {% include 'movies/partials/homepage_movies_cards.html' %}
    </div>
  </section>"""
        content = content[:start_idx] + new_section + content[end_idx + len(end_tag):]
        print("Updated moviesSection in home.html")

if css_target in content and '.weekly-cycle-badge' not in content:
    content = content.replace(css_target, css_replacement)
    print("Added CSS for weekly-cycle-badge")

# 3. Add script for refreshWeeklyMovies
script_addition = """
    // ==================================================
    // AUTOMATED WEEKLY FRIDAY MOVIES REFRESH & LIVE API
    // ==================================================
    function refreshWeeklyMovies(forceSync = false) {
      const btn = document.getElementById('refreshWeeklyMoviesBtn');
      const icon = document.getElementById('refreshWeeklyIcon');
      const rail = document.getElementById('homepageMoviesRail');
      const badgeText = document.getElementById('weeklyCycleText');
      const alertBox = document.getElementById('homepageMoviesAlert');
      const alertMsg = document.getElementById('homepageMoviesAlertMsg');

      if (icon) icon.classList.add('fa-spin');
      if (rail) rail.style.opacity = '0.45';

      const url = '/movies/api/weekly-movies/' + (forceSync ? '?force_sync=1' : '');
      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function(res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function(data) {
          if (data.success && data.html) {
            if (rail) {
              rail.innerHTML = data.html;
              rail.style.opacity = '1';
            }
            if (badgeText && data.cycle_label) {
              badgeText.textContent = data.cycle_label;
            }
            if (alertBox) alertBox.classList.add('d-none');
          } else {
            throw new Error(data.error || 'Failed to fetch weekly movies');
          }
        })
        .catch(function(err) {
          console.warn('Weekly movie refresh failed, retaining current schedule:', err);
          if (rail) rail.style.opacity = '1';
          if (alertBox && alertMsg) {
            alertMsg.textContent = 'Unable to reach TMDB for latest Friday updates. Showing all current bookable showtimes.';
            alertBox.classList.remove('d-none');
            setTimeout(function() { alertBox.classList.add('d-none'); }, 5000);
          }
        })
        .finally(function() {
          if (icon) icon.classList.remove('fa-spin');
        });
    }

    document.getElementById('refreshWeeklyMoviesBtn')?.addEventListener('click', function(e) {
      e.preventDefault();
      refreshWeeklyMovies(true);
    });
"""

if 'refreshWeeklyMovies' not in content:
    # Insert before </script>
    script_close = "</script>"
    last_script_idx = content.rfind(script_close)
    if last_script_idx != -1:
        content = content[:last_script_idx] + script_addition + "\n  " + content[last_script_idx:]
        print("Appended JavaScript to home.html")

with open(home_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Saved updated home.html successfully.")

