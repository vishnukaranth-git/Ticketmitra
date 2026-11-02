import os
import re

home_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'home.html')
with open(home_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. New 3 Categories Sections Markup
three_categories_html = """  <!-- ==================================================
       CATEGORY A: TRENDING & BOOKING OPEN
       Most Anticipated & High-Demand Movies With Active Bookings
       ================================================== -->
  <section class="mb-5 pt-2" id="moviesSection">
    <div class="d-flex justify-content-between align-items-end section-editorial-header flex-wrap" style="gap: 12px;">
      <div>
        <div class="d-flex align-items-center flex-wrap" style="gap: 8px;">
          <div class="tracker-tag mb-0" style="background: rgba(220, 20, 60, 0.15); color: #FF4D6D; border: 1px solid rgba(220, 20, 60, 0.35);">
            <i class="fas fa-fire"></i> TRENDING & BOOKING OPEN
          </div>
          <span class="weekly-cycle-badge" id="weeklyCycleBadge" title="Automated Friday release cycle for Indian cinema">
            <i class="fas fa-calendar-check mr-1 text-warning"></i>
            <span id="weeklyCycleText">{{ friday_cycle_label|default:"Friday Release Cycle" }}</span>
          </span>
        </div>
        <h2 class="section-main-heading mt-1 mb-0">Trending & High Demand</h2>
        <p class="text-muted small mb-0 mt-1" style="color: #94A3B8 !important;">Top anticipated franchise sequels, blockbusters, and high-demand releases with tickets currently available.</p>
      </div>
      <div class="rail-controls-box d-flex align-items-center" style="gap: 8px;">
        <button class="rail-control-btn" id="refreshWeeklyMoviesBtn" type="button" title="Refresh live demand rankings" aria-label="Refresh Movies">
          <i class="fas fa-sync-alt" id="refreshWeeklyIcon" style="font-size: 11px;"></i>
        </button>
        <button class="rail-control-btn" onclick="manualScroll('trendingBookingRail', -360)" aria-label="Previous Movies">
          <i class="fas fa-chevron-left" style="font-size: 12px;"></i>
        </button>
        <button class="rail-control-btn" onclick="manualScroll('trendingBookingRail', 360)" aria-label="Next Movies">
          <i class="fas fa-chevron-right" style="font-size: 12px;"></i>
        </button>
      </div>
    </div>

    <div id="homepageMoviesAlert" class="alert d-none my-2" style="background: rgba(21, 28, 48, 0.95); border: 1px solid rgba(214, 31, 69, 0.4); color: #F2E9DC; font-size: 13px; border-radius: 6px;">
      <i class="fas fa-info-circle text-warning mr-2"></i>
      <span id="homepageMoviesAlertMsg">Unable to refresh live rankings right now. Showing scheduled bookable showtimes.</span>
    </div>

    <div class="carousel-scroll-rail continuous-rail position-relative" id="trendingBookingRail" data-auto-scroll="true" style="transition: opacity 0.25s ease;">
      {% for movie in trending_booking_open %}
        {% include 'movies/partials/categorized_movie_card.html' with movie=movie %}
      {% empty %}
        <div class="p-4 text-center w-100" style="color: var(--text-warmstone-sub); min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
          <i class="fas fa-film mb-2" style="font-size: 26px; opacity: 0.5;"></i>
          <p class="mb-0">No trending movies currently open for booking.</p>
        </div>
      {% endfor %}
    </div>
  </section>

  <!-- ==================================================
       CATEGORY B: UPCOMING ANTICIPATED MOVIES
       Major Upcoming Theatrical Releases (COMING SOON)
       ================================================== -->
  <section class="mb-5 pt-2" id="upcomingAnticipatedSection">
    <div class="d-flex justify-content-between align-items-end section-editorial-header flex-wrap" style="gap: 12px;">
      <div>
        <div class="tracker-tag mb-0" style="background: rgba(245, 158, 11, 0.15); color: #FBBF24; border: 1px solid rgba(245, 158, 11, 0.35);">
          <i class="fas fa-clock"></i> COMING SOON TO THEATRES
        </div>
        <h2 class="section-main-heading mt-1 mb-0">Upcoming Anticipated Movies</h2>
        <p class="text-muted small mb-0 mt-1" style="color: #94A3B8 !important;">Major upcoming theatrical productions, multistarrers, and anticipated titles releasing soon.</p>
      </div>
      <div class="rail-controls-box d-flex align-items-center" style="gap: 8px;">
        <button class="rail-control-btn" onclick="manualScroll('upcomingAnticipatedRail', -360)" aria-label="Previous Upcoming">
          <i class="fas fa-chevron-left" style="font-size: 12px;"></i>
        </button>
        <button class="rail-control-btn" onclick="manualScroll('upcomingAnticipatedRail', 360)" aria-label="Next Upcoming">
          <i class="fas fa-chevron-right" style="font-size: 12px;"></i>
        </button>
      </div>
    </div>

    <div class="carousel-scroll-rail continuous-rail position-relative" id="upcomingAnticipatedRail" data-auto-scroll="false" style="transition: opacity 0.25s ease;">
      {% for movie in upcoming_anticipated %}
        {% include 'movies/partials/categorized_movie_card.html' with movie=movie %}
      {% empty %}
        <div class="p-4 text-center w-100" style="color: var(--text-warmstone-sub); min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
          <i class="fas fa-calendar mb-2" style="font-size: 26px; opacity: 0.5;"></i>
          <p class="mb-0">No upcoming titles scheduled right now.</p>
        </div>
      {% endfor %}
    </div>
  </section>

  <!-- ==================================================
       CATEGORY C: NOW SHOWING
       Other Current Theatrical Movies Running In Theatres
       ================================================== -->
  <section class="mb-5 pt-2" id="nowShowingSection">
    <div class="d-flex justify-content-between align-items-end section-editorial-header flex-wrap" style="gap: 12px;">
      <div>
        <div class="tracker-tag mb-0">
          <i class="fas fa-film"></i> IN THEATRES NOW
        </div>
        <h2 class="section-main-heading mt-1 mb-0">Now Showing</h2>
        <p class="text-muted small mb-0 mt-1" style="color: #94A3B8 !important;">Explore all current theatrical movies playing in cinemas near you with live showtimes.</p>
      </div>
      <div class="rail-controls-box d-flex align-items-center" style="gap: 8px;">
        <button class="rail-control-btn" onclick="manualScroll('nowShowingRail', -360)" aria-label="Previous Now Showing">
          <i class="fas fa-chevron-left" style="font-size: 12px;"></i>
        </button>
        <button class="rail-control-btn" onclick="manualScroll('nowShowingRail', 360)" aria-label="Next Now Showing">
          <i class="fas fa-chevron-right" style="font-size: 12px;"></i>
        </button>
      </div>
    </div>

    <div class="carousel-scroll-rail continuous-rail position-relative" id="nowShowingRail" data-auto-scroll="false" style="transition: opacity 0.25s ease;">
      {% for movie in now_showing_movies %}
        {% include 'movies/partials/categorized_movie_card.html' with movie=movie %}
      {% empty %}
        <div class="p-4 text-center w-100" style="color: var(--text-warmstone-sub); min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
          <i class="fas fa-film mb-2" style="font-size: 26px; opacity: 0.5;"></i>
          <p class="mb-0">No other movies currently showing.</p>
        </div>
      {% endfor %}
    </div>
  </section>"""

# Replace moviesSection with the new 3-categories HTML
m1 = content.find('<section class="mb-5 pt-2" id="moviesSection">')
m2 = content.find('<section class="mb-5" id="cinemas-around-you">')

if m1 != -1 and m2 != -1:
    content = content[:m1] + three_categories_html + "\n\n  " + content[m2:]
    print("Replaced moviesSection with 3 categories")
else:
    print(f"Could not find moviesSection boundaries: m1={m1}, m2={m2}")

# Remove old upcomingSection if present
up_start = content.find('id="upcomingSection"')
if up_start != -1:
    sec_tag = '<section class="mb-5 pt-2" id="upcomingSection">'
    sec_idx = content.find(sec_tag)
    if sec_idx != -1:
        end_idx = content.find('</section>', sec_idx)
        if end_idx != -1:
            content = content[:sec_idx] + content[end_idx + len('</section>'):]
            print("Removed old upcomingSection")

# Add JavaScript for refreshWeeklyMovies
js_addition = """
  // ==================================================
  // AUTOMATED WEEKLY FRIDAY MOVIES REFRESH & LIVE API
  // ==================================================
  function refreshWeeklyMovies(forceSync = false) {
    const btn = document.getElementById('refreshWeeklyMoviesBtn');
    const icon = document.getElementById('refreshWeeklyIcon');
    const trendingRail = document.getElementById('trendingBookingRail');
    const upcomingRail = document.getElementById('upcomingAnticipatedRail');
    const nowShowingRail = document.getElementById('nowShowingRail');
    const badgeText = document.getElementById('weeklyCycleText');
    const alertBox = document.getElementById('homepageMoviesAlert');
    const alertMsg = document.getElementById('homepageMoviesAlertMsg');

    if (icon) icon.classList.add('fa-spin');
    if (trendingRail) trendingRail.style.opacity = '0.45';
    if (upcomingRail) upcomingRail.style.opacity = '0.45';
    if (nowShowingRail) nowShowingRail.style.opacity = '0.45';

    const url = '/movies/api/weekly-movies/' + (forceSync ? '?force_sync=1' : '');
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function(data) {
        if (data.success) {
          if (trendingRail && data.trending_html) {
            trendingRail.innerHTML = data.trending_html;
            trendingRail.style.opacity = '1';
          }
          if (upcomingRail && data.upcoming_html) {
            upcomingRail.innerHTML = data.upcoming_html;
            upcomingRail.style.opacity = '1';
          }
          if (nowShowingRail && data.now_showing_html) {
            nowShowingRail.innerHTML = data.now_showing_html;
            nowShowingRail.style.opacity = '1';
          }
          if (badgeText && data.cycle_label) {
            badgeText.textContent = data.cycle_label;
          }
          if (alertBox) alertBox.classList.add('d-none');
        } else {
          throw new Error(data.error || 'Failed to fetch categorized movies');
        }
      })
      .catch(function(err) {
        console.warn('Movie refresh failed, retaining current schedule:', err);
        if (trendingRail) trendingRail.style.opacity = '1';
        if (upcomingRail) upcomingRail.style.opacity = '1';
        if (nowShowingRail) nowShowingRail.style.opacity = '1';
        if (alertBox && alertMsg) {
          alertMsg.textContent = 'Unable to refresh live rankings right now. Showing current bookable showtimes.';
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
    script_close = "</script>"
    idx = content.rfind(script_close)
    if idx != -1:
        content = content[:idx] + js_addition + "\n" + content[idx:]
        print("Added refreshWeeklyMovies JS to home.html")

with open(home_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Finished saving updated home.html")

