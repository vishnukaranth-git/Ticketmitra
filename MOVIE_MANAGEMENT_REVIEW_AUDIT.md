# TicketMitra Movie Management, Reviews, and Discovery Audit

Audit date: 2026-11-02

## Scope and verification notes

The audit followed the existing Django movie, review, moderation, and recommendation paths. The changes reuse the existing models and routes; no database schema, migration, authentication, booking, seat reservation, payment, or trailer-provider integration was changed. Tests used Django's isolated test database with actual model records and requests. The production database was not modified.

Status means the behavior was exercised or directly verified in code/tests. “Partial” identifies a specific limitation rather than treating a visible control as proof of functionality.

## A. Movie management – admin

| Requirement | Status | Evidence and verified behavior | Missing or limitation | Relevant files |
|---|---|---|---|---|
| A1. Add, edit, and delete movies | Complete | Custom staff movie management supports add/edit/delete. Admin CRUD test confirms an administrator's movie changes appear on the actual movie detail page. | None found in the audited paths. | `movies/admin_views.py`, `movies/admin.py`, `templates/admin/movies_list.html`, `movies/test_admin.py` |
| A2. Manage genres and languages | Complete | Django admin registers Genre and Language; creation through the real admin add forms is tested. Movie admin exposes genre/language relationships. | None found. | `movies/models.py`, `movies/admin.py`, `movies/test_admin.py` |
| A3. Manage cast members | Complete | CastMember is registered and editable in Django admin; creation through its admin form is tested. | None found. | `movies/models.py`, `movies/admin.py`, `movies/test_admin.py` |
| A4. Manage theatres and show schedules | Complete | Theatre/screen management is present, and `/admin/showtimes/` creates a Theater showtime plus 32 available seats. The schedule creation path is tested against database records. | No standalone admin edit action for an existing showtime was found in the custom schedule view; existing Django admin model registrations remain available. | `movies/admin.py`, `movies/admin_views.py`, `movies/test_admin.py`, `Ticketmitra/urls.py` |
| A5. Add multiple movie posters | Complete | Movie has a related MoviePoster collection and the standard Movie admin includes a poster inline. | None found. | `movies/models.py`, `movies/admin.py` |
| A6. Add age certification, duration, and detailed descriptions | Complete | Existing Movie fields and admin forms cover age certification, runtime, and description. Custom admin no longer fabricates values when metadata is blank; blank metadata stays blank and new records remain drafts. | None found in data entry. Completeness depends on the administrator supplying source data. | `movies/models.py`, `movies/admin.py`, `movies/admin_views.py`, `templates/admin/movies_list.html`, `movies/test_admin.py` |
| A7. Securely embed YouTube trailers | Partial | Embed URLs are now accepted only over HTTPS from recognized YouTube hosts and supported URL forms with a valid 11-character video ID. Watch links derive from the validated URL. Spoofed-host input is covered by a safety test. | Host/ID validation cannot establish that the video belongs to the movie or that the uploader is an official distributor. There is no channel verification in the current model/API path. | `movies/models.py`, `movies/views.py`, `movies/tests.py`, `templates/movies/movie_detail.html` |
| A8. Verify admin changes appear on the actual website | Complete | Test adds/edits movie through the custom admin and checks the movie detail response. Schedule test verifies the Theater row and generated Seat rows are persisted; public movie detail reads current movie and showtime data. | External cache/CDN behavior was not part of this local Django test. | `movies/admin_views.py`, `movies/views.py`, `movies/test_admin.py` |

## B. Movie ratings and reviews – registered users

| Requirement | Status | Evidence and verified behavior | Missing or limitation | Relevant files |
|---|---|---|---|---|
| B1. Submit star rating and written review from movie detail | Complete | Movie detail includes the rating selector, text entry, and submit flow. AJAX submission persists the review and updates the review list and aggregate without a page reload. | None found. | `templates/movies/movie_detail.html`, `movies/views.py`, `movies/tests.py` |
| B2. Review only after completing a booking and watching the movie | Complete | Staff can check a ticket in from booking management only after its movie runtime has elapsed. The check-in is recorded on the booking; review submission additionally requires a confirmed booking and that check-in. | Check-in records staff-verified attendance rather than an automated gate scan. Existing bookings remain unchecked until staff verify them; no attendance is backfilled from purchase records. | `movies/models.py`, `movies/migrations/0018_booking_attended_at.py`, `movies/admin_views.py`, `templates/admin/bookings_list.html`, `movies/views.py`, `movies/tests.py` |
| B3. Backend verifies booking eligibility | Complete | The add-review endpoint independently checks a confirmed booking, elapsed movie runtime, and staff check-in; an ineligible direct API/form POST returns 403. | None found. | `movies/views.py`, `movies/models.py`, `movies/tests.py` |
| B4. Users can edit their own reviews | Complete | Edit endpoint checks ownership server-side; AJAX editing saves and updates the existing card and aggregate. | None found. | `movies/views.py`, `templates/movies/movie_detail.html`, `movies/tests.py` |
| B5. Users can report inappropriate reviews | Complete | Authenticated report endpoint records a unique report per reporter/review, marks the review reported, and prevents self-reporting and duplicate reports. | None found in the audited interaction. | `movies/models.py`, `movies/views.py`, `movies/tests.py` |
| B6. Administrators can review and moderate reported content | Complete | Staff report queue shows real review text/reason. Approve clears reports and restores the review; dismiss removes the report and restores visibility when no reports remain. Both moderation actions are tested. | None found. | `movies/admin_views.py`, `movies/admin.py`, `templates/admin/reports_list.html`, `templates/admin/reviews_list.html`, `movies/tests.py` |
| B7. Verified viewer badges only for eligible users | Complete | Badge derives from an attended timestamp on a confirmed booking for that user/movie, with the movie runtime elapsed. Public reviews and aggregates require the same eligibility. | Historical reviews without an attendance record no longer contribute to verified review displays and averages unless staff validate attendance. | `movies/models.py`, `movies/views.py`, `templates/movies/movie_detail.html`, `movies/tests.py` |
| B8. Average rating calculated from valid user ratings | Complete | Average/count are computed from ratings 1–5 that are not reported and belong to users with a qualifying past confirmed booking. Submission/edit/report tests verify updates and exclusion. | None found in the audited calculation. | `movies/models.py`, `movies/views.py`, `movies/tests.py` |
| B9. Prevent multiple reviews per movie unless editing | Complete | Database uniqueness is defined for user/movie; endpoint also detects duplicates and handles concurrent duplicate creation. Existing review edits update that row. | None found. | `movies/models.py`, `movies/views.py`, `movies/tests.py` |

## C. Movie discovery

| Requirement | Status | Evidence and verified behavior | Missing or limitation | Relevant files |
|---|---|---|---|---|
| C1. Similar movies based on genre and language | Complete | Query prioritizes matching genre and language from active catalog movies, excludes drafts and the current movie, and returns no unrelated fallback when matching metadata is absent. | Results depend on catalog metadata quality. | `movies/models.py`, `movies/views.py`, `templates/movies/movie_detail.html`, `movies/tests.py` |
| C2. Trending movies | Complete | Movie detail recommendation list is selected from actual active, non-draft theatrical catalog records ordered by popularity, vote count, and release date; the real section is rendered. | The ranking is based on stored catalog metrics, not a separate real-time external trend feed. | `movies/views.py`, `templates/movies/movie_detail.html`, `movies/tests.py` |
| C3. Recently released movies | Complete | Section selects actual active, non-draft theatrical movies released in the preceding 14 days and orders by release date. | Requires a populated release date. | `movies/views.py`, `templates/movies/movie_detail.html`, `movies/tests.py` |
| C4. Recommendations use actual data and update appropriately | Complete | Similar, trending, and recent lists are database querysets, and rendering tests verify actual records appear while drafts are excluded. They update as catalog fields and dates change. | No separate recommendation cache invalidation is needed in the current query path. | `movies/models.py`, `movies/views.py`, `templates/movies/movie_detail.html`, `movies/tests.py` |

## Changes implemented

- Restricted public review lists and aggregate ratings to valid, unreported reviews from users with a qualifying completed booking.
- Enforced review eligibility on the server, blocked duplicate creation, retained owner-only editing, and added asynchronous create/edit presentation updates.
- Corrected reporting and moderation behavior so reported content is hidden from public ratings and can be restored by moderation.
- Added actual similar, trending, and recent-release recommendation sections to movie detail; removed fabricated rating display values and unrelated fallback recommendations.
- Hardened YouTube embed URL validation and fixed admin review/report templates that referenced fields not present on the models.
- Removed misleading custom movie-admin metadata defaults and added tests for catalog reflection, schedule persistence, generated seats, admin taxonomy/cast management, and review/discovery behavior.
- Added a nullable booking attendance timestamp and staff check-in controls to booking management. The backend only allows check-in for confirmed bookings after the movie runtime elapses; review eligibility, verified badges, and aggregate ratings now require that check-in.

## Verification results

- Full movie app suite: **102 tests passed** (`manage.py test movies --noinput`), with Django system checks reporting no issues.
- Focused coverage includes: eligible review create/edit and persistence; rejection before check-in, before runtime completion, and for cancelled/future bookings; staff check-in; duplicate requests; report/moderation and aggregate behavior; active/draft recommendation selection; admin movie CRUD reflected on movie detail; real schedule creation and generated seats.
- Additive migration `0018_booking_attended_at` was applied to the local project database. Existing rows remain unchanged and unchecked; no booking, payment, or seat-reservation flow was modified.

## Attendance rollout note

New check-ins are recorded by authorized cinema staff after validating the ticket for a completed screening. Legacy bookings are deliberately not marked attended automatically; staff must validate those tickets before related reviews can contribute to verified review displays and averages. This avoids manufacturing attendance history from purchase records.
