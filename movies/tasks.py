import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .models import Booking
from .services.ticket_pdf_service import generate_ticket_pdf

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_jitter=True,
    autoretry_for=(Exception,),
)
def send_booking_confirmation_email_task(self, booking_id, recipient_email=None):
    """
    Asynchronous Celery background task to:
    1. Retrieve confirmed booking details.
    2. Generate high-quality PDF ticket containing QR code and movie/screen/seat information.
    3. Send confirmation email to user with PDF ticket attached.
    4. Automatically retry up to 3 times on delivery or network failure using Celery autoretry.
    """
    try:
        booking = Booking.objects.select_related(
            'user', 'movie', 'theater', 'theater__screen', 'seat'
        ).get(id=booking_id)
    except Booking.DoesNotExist:
        logger.error(f"Booking #{booking_id} does not exist. Aborting ticket email task.")
        return False

    to_email = recipient_email or (booking.user.email if booking.user else None)
    if not to_email:
        logger.warning(f"No valid recipient email address for booking #{booking_id}. Skipping email.")
        return False

    # Generate professional PDF Ticket
    pdf_bytes = generate_ticket_pdf(booking)

    movie_title = booking.movie.get_display_title()
    theater_name = booking.theater.name
    show_time = booking.theater.time.strftime('%a, %b %d, %Y at %I:%M %p')
    ref_id = f"#TM-BK-{booking.id:06d}"

    subject = f"🎟️ Booking Confirmed: {movie_title} at {theater_name} [{ref_id}]"

    text_body = f"""Hello {booking.user.get_full_name() or booking.user.username},

Your cinema ticket booking for {movie_title} is confirmed!

Booking Reference: {ref_id}
Theater: {theater_name}
Showtime: {show_time}
Seat: {booking.seat.seat_number}

Your official admission ticket is attached as a PDF with a verification QR code for direct gate entry.

Thank you for choosing TicketMitra Cinemas!
"""

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0F172A; color: #F8FAFC; border-radius: 12px; overflow: hidden; border: 1px solid #1E293B;">
        <div style="background: #E63946; padding: 20px; text-align: center;">
            <h1 style="margin: 0; color: #FFFFFF; font-size: 22px;">TicketMitra Cinemas</h1>
            <p style="margin: 4px 0 0 0; color: #FEE2E2; font-size: 13px;">Official Digital Admission Ticket</p>
        </div>
        <div style="padding: 24px;">
            <h2 style="color: #38BDF8; font-size: 18px; margin-top: 0;">🎉 You're going to the movies!</h2>
            <p style="color: #CBD5E1; font-size: 14px;">Hi <b>{booking.user.get_full_name() or booking.user.username}</b>,</p>
            <p style="color: #CBD5E1; font-size: 14px;">Your booking has been verified and confirmed. Your official PDF pass with entry QR code is attached to this email.</p>
            
            <table style="width: 100%; border-collapse: collapse; background: #1E293B; border-radius: 8px; margin: 20px 0; font-size: 14px;">
                <tr>
                    <td style="padding: 12px; color: #94A3B8; border-bottom: 1px solid #334155;">Movie:</td>
                    <td style="padding: 12px; color: #FFFFFF; font-weight: bold; border-bottom: 1px solid #334155;">{movie_title}</td>
                </tr>
                <tr>
                    <td style="padding: 12px; color: #94A3B8; border-bottom: 1px solid #334155;">Theater:</td>
                    <td style="padding: 12px; color: #FFFFFF; border-bottom: 1px solid #334155;">{theater_name}</td>
                </tr>
                <tr>
                    <td style="padding: 12px; color: #94A3B8; border-bottom: 1px solid #334155;">Showtime:</td>
                    <td style="padding: 12px; color: #38BDF8; font-weight: bold; border-bottom: 1px solid #334155;">{show_time}</td>
                </tr>
                <tr>
                    <td style="padding: 12px; color: #94A3B8;">Booking Reference:</td>
                    <td style="padding: 12px; color: #E63946; font-weight: bold;">{ref_id}</td>
                </tr>
            </table>

            <div style="background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 8px; padding: 14px; text-align: center; color: #4ADE80; font-size: 13px; margin-bottom: 20px;">
                📲 <b>Attached Pass:</b> Scan the QR code in the attached PDF ticket at the cinema gate for direct entry.
            </div>
            
            <p style="color: #64748B; font-size: 12px; text-align: center; margin-bottom: 0;">
                Have questions? Visit your TicketMitra Booking History to view or re-download your tickets anytime.
            </p>
        </div>
    </div>
    """

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'TicketMitra <tickets@ticketmitra.com>'),
        to=[to_email]
    )
    msg.attach_alternative(html_body, "text/html")
    msg.attach(
        filename=f"TicketMitra_Ticket_{booking.id}.pdf",
        content=pdf_bytes,
        mimetype="application/pdf"
    )
    msg.send(fail_silently=False)
    logger.info(f"Booking #{booking_id} confirmation email with PDF ticket sent to {to_email}.")
    return True


# ── Periodic TMDB Sync Task ────────────────────────────────────────────────────

@shared_task(name='movies.tasks.sync_tmdb_movies_task')
def sync_tmdb_movies_task():
    """
    Periodic Celery task: sync now-playing and upcoming movies from TMDB.
    Scheduled via CELERY_BEAT_SCHEDULE (daily at 2 AM UTC).
    Also callable manually: from movies.tasks import sync_tmdb_movies_task; sync_tmdb_movies_task.delay()
    """
    from django.core.management import call_command
    logger.info("Periodic sync_tmdb_movies_task: starting TMDB movie sync...")
    try:
        call_command('sync_tmdb_movies', '--all', '--pages=2')
        logger.info("Periodic sync_tmdb_movies_task: completed successfully.")
        return {'status': 'success'}
    except Exception as e:
        logger.error(f"Periodic sync_tmdb_movies_task: failed — {e}")
        raise


@shared_task(name='movies.tasks.cleanup_screenings_task')
def cleanup_screenings_task():
    """
    Periodic Celery task: deactivate past screenings and update movie statuses.
    Scheduled via CELERY_BEAT_SCHEDULE (hourly).
    Also callable manually: from movies.tasks import cleanup_screenings_task; cleanup_screenings_task.delay()
    """
    from django.core.management import call_command
    logger.info("Periodic cleanup_screenings_task: starting screening cleanup...")
    try:
        call_command('cleanup_screenings')
        logger.info("Periodic cleanup_screenings_task: completed successfully.")
        return {'status': 'success'}
    except Exception as e:
        logger.error(f"Periodic cleanup_screenings_task: failed — {e}")
        raise


@shared_task(name='movies.tasks.weekly_friday_movie_refresh_task')
def weekly_friday_movie_refresh_task(force=False):
    """
    Periodic Celery Beat task that automatically runs every Friday at 00:00 (midnight).
    1. Fetches and synchronizes the latest Indian theatrical releases from TMDB (region=IN).
    2. Discovers new releases for the current Friday cycle and next 7 days.
    3. Guarantees that movies appearing in the main Movies section have active bookable showtimes.
    4. Automatically removes movies whose showtimes have expired or that are no longer relevant.
    5. Safely retains existing movie records if TMDB API or network encounters an issue.
    """
    from movies.services.weekly_sync_service import sync_weekly_movies
    logger.info("[Celery Beat] weekly_friday_movie_refresh_task: Starting Friday movie refresh...")
    try:
        result = sync_weekly_movies(force=force)
        logger.info(f"[Celery Beat] weekly_friday_movie_refresh_task completed: {result.get('message')}")
        return result
    except Exception as exc:
        logger.error(f"[Celery Beat] weekly_friday_movie_refresh_task error: {exc}")
        raise

