from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from movies.models import (
    Booking,
    Movie,
    Payment,
    Screen,
    Seat,
    SeatReservation,
    Theater,
)
from movies.services.ticket_pdf_service import (
    generate_qr_code_image,
    generate_ticket_pdf,
)
from movies.tasks import send_booking_confirmation_email_task


class TicketGenerationAndCeleryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='test_cinephile', password='password123', email='cinephile@test.com')
        self.other_user = User.objects.create_user(username='intruder', password='password123', email='intruder@test.com')

        # Movie
        self.movie = Movie.objects.create(
            name='Interstellar IMAX',
            title='Interstellar IMAX',
            original_title='Interstellar',
            original_language='en',
            runtime=169,
            age_certification='UA',
            rating=8.9,
            popularity=95.0,
            release_date=timezone.now().date() - timedelta(days=100),
            status='CURRENT'
        )

        # Screen
        self.screen = Screen.objects.create(
            theater_name='PVR Superplex Koramangala',
            name='IMAX Screen 1',
            screen_type='IMAX',
            capacity=60
        )

        # Theater / Showtime
        self.theater = Theater.objects.create(
            name='PVR Superplex Koramangala',
            movie=self.movie,
            screen=self.screen,
            time=timezone.now() + timedelta(days=2),
            city='Bengaluru',
            address='The Forum Mall, Koramangala',
            price=320.00,
            active=True
        )

        # Seats
        self.seat1 = Seat.objects.create(theater=self.theater, screen=self.screen, seat_number='H12', is_booked=True)
        self.seat2 = Seat.objects.create(theater=self.theater, screen=self.screen, seat_number='H13', is_booked=True)

        # Booking
        self.booking = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater,
            amount=320.00,
            status='CONFIRMED'
        )
        self.companion_booking = Booking.objects.create(
            user=self.user,
            seat=self.seat2,
            movie=self.movie,
            theater=self.theater,
            amount=320.00,
            status='CONFIRMED'
        )

        # Payment
        self.payment = Payment.objects.create(
            user=self.user,
            amount=640.00,
            currency='INR',
            provider='STRIPE',
            order_id='order_test_interstellar_123',
            payment_id='pi_test_stripe_verified_999',
            status='SUCCESS',
            booking=self.booking
        )
        self.payment.bookings.set([self.booking, self.companion_booking])

    def test_qr_code_generation(self):
        """Generates valid PNG image buffer for QR code."""
        buf = generate_qr_code_image("https://ticketmitra.com/verify/test")
        self.assertIsNotNone(buf)
        data = buf.getvalue()
        # PNG signature check: \x89PNG\r\n\x1a\n
        self.assertTrue(data.startswith(b'\x89PNG'))

    def test_pdf_ticket_generation_contains_all_details(self):
        """Generates a professional PDF containing all required cinema and booking details."""
        pdf_bytes = generate_ticket_pdf(self.booking)
        self.assertIsNotNone(pdf_bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        # PDF file signature check
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))

    def test_celery_task_send_confirmation_email_with_pdf(self):
        """Celery task generates PDF ticket and sends email with attachment."""
        mail.outbox.clear()
        result = send_booking_confirmation_email_task(self.booking.id, recipient_email='cinephile@test.com')
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)

        sent_mail = mail.outbox[0]
        self.assertIn('Interstellar IMAX', sent_mail.subject)
        self.assertIn(f'#TM-BK-{self.booking.id:06d}', sent_mail.subject)
        self.assertEqual(sent_mail.to, ['cinephile@test.com'])

        # Check PDF attachment
        self.assertEqual(len(sent_mail.attachments), 1)
        filename, content, mimetype = sent_mail.attachments[0]
        self.assertEqual(filename, f"TicketMitra_Ticket_{self.booking.id}.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b'%PDF-'))

    @patch('movies.tasks.send_booking_confirmation_email_task.retry')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_celery_task_retry_on_failure(self, mock_send, mock_retry):
        """Celery task retries automatically on delivery errors."""
        from celery.exceptions import Retry
        mock_send.side_effect = Exception("SMTP Connection Failed")
        mock_retry.side_effect = Retry()

        with self.assertRaises(Retry):
            send_booking_confirmation_email_task(self.booking.id, recipient_email='cinephile@test.com')
        mock_retry.assert_called_once()

    def test_download_ticket_pdf_authorized_user(self):
        """Authorized user can download their ticket PDF."""
        self.client.login(username='test_cinephile', password='password123')
        url = reverse('download_ticket_pdf', kwargs={'booking_id': self.booking.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn(f'filename="TicketMitra_Ticket_{self.booking.id}.pdf"', res['Content-Disposition'])
        self.assertTrue(res.content.startswith(b'%PDF-'))

    def test_download_ticket_pdf_unauthorized_user(self):
        """Another user cannot download someone else's ticket."""
        self.client.login(username='intruder', password='password123')
        url = reverse('download_ticket_pdf', kwargs={'booking_id': self.booking.id})
        res = self.client.get(url)
        # Should redirect with error message
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('my_bookings'), res.url)

    def test_booking_history_page_includes_download_pdf_links(self):
        """Booking history template renders Download PDF buttons."""
        self.client.login(username='test_cinephile', password='password123')
        res = self.client.get(reverse('my_bookings'))
        self.assertEqual(res.status_code, 200)
        expected_download_url = reverse('download_ticket_pdf', kwargs={'booking_id': self.booking.id})
        self.assertContains(res, expected_download_url)
        self.assertContains(res, "PDF")

    @patch('movies.tasks.send_booking_confirmation_email_task.delay')
    def test_booking_flow_dispatches_celery_task_and_never_blocks_on_error(self, mock_delay):
        """Booking flow dispatches email asynchronously and never fails even if task queuing errors."""
        mock_delay.side_effect = Exception("Celery broker temporarily unreachable")

        # Create active reservation for direct confirmation
        seat_c = Seat.objects.create(theater=self.theater, screen=self.screen, seat_number='J10', is_booked=False)
        reservation = SeatReservation.objects.create(
            user=self.user,
            theater=self.theater,
            expires_at=timezone.now() + timedelta(minutes=5),
            total_amount=320.00,
            status='ACTIVE'
        )
        reservation.seats.add(seat_c)

        self.client.login(username='test_cinephile', password='password123')
        url = reverse('confirm_payment', kwargs={'reservation_id': reservation.id})
        res = self.client.post(url)
        # Booking must succeed and redirect to ticket page despite Celery exception
        self.assertEqual(res.status_code, 302)
        self.assertIn('/ticket/', res.url)
        # Seat must be booked
        seat_c.refresh_from_db()
        self.assertTrue(seat_c.is_booked)
