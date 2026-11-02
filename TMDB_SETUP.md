# TicketMitra — TMDB Auto-Sync Setup Guide

## Overview

TicketMitra automatically discovers and manages movies using the TMDB (The Movie Database) API.  
The system fetches Indian theatrical releases, keeps movie metadata up-to-date, and manages  
screening lifecycle status without any manual intervention.

---

## Environment Configuration

### Required `.env` Variable

```env
TMDB_API_KEY=eyJhbGci...   # TMDB v4 Read Access Token (JWT Bearer token)
```

> **Security:** The token is loaded server-side only via `settings.TMDB_API_KEY`.  
> It is **never** passed to frontend JavaScript or HTML templates.

To obtain a token:
1. Go to [https://www.themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)
2. Create an API application
3. Copy the **API Read Access Token (v4 auth)** — it starts with `eyJ`
4. Paste it as `TMDB_API_KEY` in `Ticketmitra/.env`

---

## Management Commands

### 1. Sync Movies from TMDB

```bash
# Sync both now-playing and upcoming (recommended — runs daily automatically)
py -3 manage.py sync_tmdb_movies --all

# Sync only now-playing movies (region=IN)
py -3 manage.py sync_tmdb_movies --now-playing

# Sync only upcoming movies (region=IN)
py -3 manage.py sync_tmdb_movies --upcoming

# Fetch 3 pages per endpoint (more movies)
py -3 manage.py sync_tmdb_movies --all --pages=3

# Preview without saving (dry run)
py -3 manage.py sync_tmdb_movies --all --dry-run
```

### 2. Cleanup Screenings

```bash
# Deactivate past screenings, update movie statuses, expire stale reservations
py -3 manage.py cleanup_screenings

# Preview without saving
py -3 manage.py cleanup_screenings --dry-run
```

### 3. Other Useful Commands

```bash
# Full curated sync (25-30 Indian + global movies, creates showtimes)
py -3 manage.py sync_current_movies

# Audit and fix specific movie release dates and statuses
py -3 manage.py audit_movie_statuses

# Import a specific movie by searching TMDB keyword
py -3 manage.py import_tmdb_movies --search "Pushpa 2"

# Release expired seat reservations
py -3 manage.py release_expired_reservations
```

---

## Movie Status Lifecycle

```
UPCOMING  →  CURRENT (Now Showing)  →  ENDED
   ↓              ↓
ADVANCE_BOOKING  (release_date > today AND advance booking open)
```

| Status           | Condition                                                                 |
|------------------|---------------------------------------------------------------------------|
| `UPCOMING`       | `release_date > today` and no advance booking showtimes                   |
| `ADVANCE_BOOKING`| `release_date > today` and advance booking is open / has future showtimes |
| `CURRENT`        | `release_date <= today` and has at least one active future screening      |
| `ENDED`          | `release_date <= today` and **no** active future screenings remaining     |
| `OTT_ONLY`       | Streaming-only title, no theatrical release                               |

Status is determined from **actual `Theater` screening records** — not a fixed number of days.

---

## Automatic Scheduling

### Local Development (No extra setup needed)

When you run `py -3 manage.py runserver`, the in-process scheduler starts automatically  
via `movies/apps.py:MoviesConfig.ready()`:

| Task                  | First Run | Repeat Interval |
|-----------------------|-----------|-----------------|
| `cleanup_screenings`  | After 60s | Every 1 hour    |
| `sync_tmdb_movies`    | After 120s| Every 24 hours  |

The scheduler runs as **daemon threads** — they stop when the server stops.  
No Redis, Celery worker, or Celery Beat process required for local dev.

### Production (with Celery Beat)

For production, install a message broker (Redis recommended) and run:

```bash
# 1. Install Redis (Ubuntu/Debian)
sudo apt install redis-server

# 2. Update .env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# 3. Start Celery worker
celery -A Ticketmitra worker -l info

# 4. Start Celery Beat scheduler
celery -A Ticketmitra beat -l info

# Or combine worker + beat (not recommended for heavy production load)
celery -A Ticketmitra worker --beat -l info
```

The `CELERY_BEAT_SCHEDULE` in `settings.py` defines:
- **Daily at 2 AM UTC**: `sync_tmdb_movies_task` (fetches 2 pages each of now_playing + upcoming)
- **Every hour**: `cleanup_screenings_task` (deactivates past screenings, expires reservations)

### Cron Alternative (No Celery)

If you prefer a simple cron without Celery:

```cron
# /etc/cron.d/ticketmitra

# Sync movies from TMDB every day at 2 AM IST (8:30 PM UTC prev day)
30 20 * * * www-data cd /path/to/Ticketmitra && py -3 manage.py sync_tmdb_movies --all >> /var/log/ticketmitra/tmdb_sync.log 2>&1

# Cleanup screenings every hour
0 * * * * www-data cd /path/to/Ticketmitra && py -3 manage.py cleanup_screenings >> /var/log/ticketmitra/cleanup.log 2>&1
```

---

## Django Admin Features

Navigate to `/admin/movies/movie/` to access:

| Feature                      | How to Use                                                         |
|------------------------------|--------------------------------------------------------------------|
| **Sync All from TMDB**       | Green button in the movie list header — syncs all movies instantly |
| **Search & Import TMDB**     | Blue button — search TMDB by title and import a specific movie     |
| **Sync selected from TMDB**  | Select movies → Actions dropdown → "🔄 Sync selected movies..."   |
| **Update release statuses**  | Select movies → Actions → "📊 Update release statuses..."         |

---

## TMDB API Endpoints Used

| Endpoint                          | Usage                                    |
|-----------------------------------|------------------------------------------|
| `/3/movie/now_playing?region=IN`  | Fetch currently playing movies in India  |
| `/3/movie/upcoming?region=IN`     | Fetch upcoming releases in India         |
| `/3/movie/{id}?append_to_response=videos,credits,release_dates,images` | Full movie details |
| `/3/search/movie?query=...`       | Search by title (admin import)           |

All requests use the Bearer token from `settings.TMDB_API_KEY` — never exposed to the client.

---

## Data Safety Guarantees

- ✅ Uses `update_or_create(tmdb_id=...)` — no duplicate movies
- ✅ Existing poster images and manually set data preserved during updates
- ✅ `Theater` records are **deactivated** (`active=False`), never deleted
- ✅ `Booking` and `SeatReservation` records are **never deleted** (historical data preserved)
- ✅ `SeatReservation.status` is set to `EXPIRED` for stale reservations (not deleted)
- ✅ TMDB token never passed to frontend templates or JavaScript

---

## Troubleshooting

### "TMDB_API_KEY is not configured"
- Ensure `TMDB_API_KEY=eyJ...` is set in `Ticketmitra/.env`
- Restart the server after modifying `.env`

### Movies not appearing on the homepage
- Run `py -3 manage.py sync_current_movies` for initial setup with showtimes
- Then run `py -3 manage.py sync_tmdb_movies --all` to keep it updated

### Screenings not being deactivated
- Run `py -3 manage.py cleanup_screenings` manually
- Or wait for the automatic hourly run (when `runserver` is active)

