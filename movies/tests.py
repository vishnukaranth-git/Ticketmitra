import hashlib
import hmac
import json
import time
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from movies.models import (
    Booking,
    CastMember,
    Genre,
    Language,
    Movie,
    Payment,
    Review,
    Seat,
    SeatReservation,
    Theater,
)
from movies.services import stripe_service
from movies.services.tmdb_service import TMDBService

razorpay_service = stripe_service


class TicketmitraFeatureTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username='viewer_alice', password='password123', email='alice@test.com')
        self.user2 = User.objects.create_user(username='viewer_bob', password='password123', email='bob@test.com')

        # Create Genres & Languages
        self.genre_action = Genre.objects.create(name='Action', tmdb_id=28)
        self.genre_scifi = Genre.objects.create(name='Sci-Fi', tmdb_id=878)
        self.lang_en = Language.objects.create(code='en', name='English')

        # Create Cast
        self.actor1 = CastMember.objects.create(name='Leonardo DiCaprio', character='Cobb')

        # Create Movie with new TMDB fields
        self.movie = Movie.objects.create(
            name='Inception',
            title='Inception',
            tmdb_id=27205,
            original_title='Inception',
            tmdb_rating=8.4,
            rating=8.4,
            vote_count=35000,
            popularity=120.5,
            release_date=timezone.now().date() - timedelta(days=365),
            runtime=148,
            age_certification='UA',
            trailer_url='https://www.youtube-nocookie.com/embed/YoHD9XEInc0',
            description='A thief who steals corporate secrets through dream-sharing technology.'
        )
        self.movie.genres.add(self.genre_action, self.genre_scifi)
        self.movie.languages.add(self.lang_en)
        self.movie.cast_members.add(self.actor1)

        # Create Theaters: One past, one future
        self.past_theater = Theater.objects.create(
            name='PVR Koramangala',
            movie=self.movie,
            time=timezone.now() - timedelta(days=2)
        )
        self.future_theater = Theater.objects.create(
            name='INOX Forum',
            movie=self.movie,
            time=timezone.now() + timedelta(days=3)
        )

        # Create Seats
        self.past_seat = Seat.objects.create(theater=self.past_theater, seat_number='A1', is_booked=True)
        self.future_seat = Seat.objects.create(theater=self.future_theater, seat_number='B1', is_booked=True)
        self.open_seat = Seat.objects.create(theater=self.future_theater, seat_number='B2', is_booked=False)

        # User1 has completed past booking for self.movie
        self.past_booking = Booking.objects.create(
            user=self.user1,
            theater=self.past_theater,
            seat=self.past_seat,
            movie=self.movie,
            attended_at=timezone.now(),
        )

        # User2 has future booking for self.movie
        self.future_booking = Booking.objects.create(
            user=self.user2,
            theater=self.future_theater,
            seat=self.future_seat,
            movie=self.movie
        )

    def test_movie_model_helpers(self):
        """Test movie display title, runtime format, and poster fallback."""
        self.assertEqual(self.movie.get_display_title(), 'Inception')
        self.assertEqual(self.movie.get_runtime_display(), '2h 28m')
        self.assertTrue(self.movie.get_poster_url())
        self.assertEqual(self.movie.get_user_rating_display(), "No reviews yet")

    def test_verified_viewer_review_submission(self):
        """User with past completed booking CAN review and gets Verified Viewer status."""
        self.client.login(username='viewer_alice', password='password123')
        url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        response = self.client.post(url, {
            'rating': '5',
            'review_text': 'Masterpiece cinema experience!'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        review = Review.objects.get(movie=self.movie, user=self.user1)
        self.assertEqual(review.rating, 5)
        self.assertTrue(review.is_verified_viewer)
        self.assertEqual(self.movie.get_average_user_rating(), 5.0)
        self.assertEqual(self.movie.get_user_rating_display(), "★ 5.0 / 5")

    def test_future_booking_cannot_review(self):
        """User whose showtime is in the future CANNOT submit a review yet."""
        self.client.login(username='viewer_bob', password='password123')
        url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        response = self.client.post(url, {
            'rating': '4',
            'review_text': 'Excited to watch!'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Review.objects.filter(movie=self.movie, user=self.user2).exists())

    def test_unbooked_user_cannot_review(self):
        """User without any booking cannot submit a review."""
        unbooked_user = User.objects.create_user(username='viewer_charlie', password='password123')
        self.client.login(username='viewer_charlie', password='password123')
        url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        response = self.client.post(url, {
            'rating': '3',
            'review_text': 'Never saw it'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Review.objects.filter(movie=self.movie, user=unbooked_user).exists())

    def test_review_requires_staff_check_in_after_completed_screening(self):
        self.past_booking.attended_at = None
        self.past_booking.save(update_fields=['attended_at'])

        self.client.login(username='viewer_alice', password='password123')
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest', 'HTTP_ACCEPT': 'application/json'}
        add_url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        rejected = self.client.post(add_url, {'rating': '5', 'review_text': 'Before check-in'}, **headers)
        self.assertEqual(rejected.status_code, 403)
        self.assertFalse(Review.objects.filter(movie=self.movie, user=self.user1).exists())
        detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': self.movie.id}))
        self.assertContains(detail, 'cinema staff must verify your ticket check-in')
        self.assertNotContains(detail, 'Write a Review')

        admin = User.objects.create_user(username='cinema_staff', password='password123', is_staff=True)
        self.client.force_login(admin)
        checked_in = self.client.post('/admin/bookings/', {
            'action': 'check_in_booking', 'booking_id': self.past_booking.id,
        }, follow=True)
        self.assertEqual(checked_in.status_code, 200)
        self.past_booking.refresh_from_db()
        self.assertIsNotNone(self.past_booking.attended_at)
        self.assertContains(checked_in, 'checked in')

        self.client.force_login(self.user1)
        submitted = self.client.post(add_url, {'rating': '5', 'review_text': 'Verified screening attendance.'}, **headers)
        self.assertEqual(submitted.status_code, 200)
        review = Review.objects.get(movie=self.movie, user=self.user1)
        self.assertTrue(review.is_verified_viewer)
        self.assertEqual(self.movie.get_review_count(), 1)

    def test_check_in_rejected_for_future_or_cancelled_booking(self):
        with self.assertRaisesMessage(ValueError, 'after the screening ends'):
            self.future_booking.check_in_attendee()
        self.past_booking.status = 'CANCELLED'
        self.past_booking.save(update_fields=['status'])
        self.past_booking.attended_at = None
        with self.assertRaisesMessage(ValueError, 'Only confirmed bookings'):
            self.past_booking.check_in_attendee()

    def test_screen_runtime_must_elapse_before_check_in(self):
        upcoming_end_theater = Theater.objects.create(
            name='Still Playing', movie=self.movie,
            time=timezone.now() - timedelta(minutes=30),
        )
        seat = Seat.objects.create(theater=upcoming_end_theater, seat_number='C1', is_booked=True)
        booking = Booking.objects.create(user=self.user1, movie=self.movie, theater=upcoming_end_theater, seat=seat)
        self.assertFalse(booking.is_show_completed)
        with self.assertRaisesMessage(ValueError, 'after the screening ends'):
            booking.check_in_attendee()

    def test_duplicate_review_prevention(self):
        """User cannot submit duplicate reviews for the same movie."""
        Review.objects.create(
            user=self.user1,
            movie=self.movie,
            booking=self.past_booking,
            rating=5,
            review_text='Initial review'
        )

        self.client.login(username='viewer_alice', password='password123')
        url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        response = self.client.post(url, {
            'rating': '4',
            'review_text': 'Attempted second review'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(Review.objects.filter(movie=self.movie, user=self.user1).count(), 1)
        self.assertEqual(Review.objects.get(movie=self.movie, user=self.user1).rating, 5)

    def test_ajax_review_create_edit_average_and_persistence(self):
        self.client.login(username='viewer_alice', password='password123')
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest', 'HTTP_ACCEPT': 'application/json'}
        create_url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        created = self.client.post(create_url, {'rating': '4', 'review_text': 'Beautifully made and memorable.'}, **headers)
        self.assertEqual(created.status_code, 200)
        payload = created.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['review']['review_count'], 1)
        self.assertEqual(payload['review']['average_rating'], 4.0)
        review = Review.objects.get(movie=self.movie, user=self.user1)
        self.assertEqual(review.booking_id, self.past_booking.id)
        self.assertEqual(self.movie.get_average_user_rating(), 4.0)

        edit_url = reverse('edit_review', kwargs={'review_id': review.id})
        edited = self.client.post(edit_url, {'rating': '5', 'review_text': 'Updated after reflection.'}, **headers)
        self.assertEqual(edited.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review_text, 'Updated after reflection.')
        self.assertEqual(edited.json()['review']['average_rating'], 5.0)

        detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': self.movie.id}))
        self.assertContains(detail, 'Updated after reflection.')
        self.assertContains(detail, '5.0')

    def test_review_api_rejects_cancelled_booking_and_duplicate(self):
        self.client.login(username='viewer_alice', password='password123')
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest', 'HTTP_ACCEPT': 'application/json'}
        url = reverse('add_review', kwargs={'movie_id': self.movie.id})
        self.past_booking.status = 'CANCELLED'
        self.past_booking.save(update_fields=['status'])
        rejected = self.client.post(url, {'rating': '5', 'review_text': 'Not eligible'}, **headers)
        self.assertEqual(rejected.status_code, 403)
        self.assertFalse(Review.objects.filter(movie=self.movie, user=self.user1).exists())
        detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': self.movie.id}))
        self.assertContains(detail, 'Verified Attendee Policy')
        self.assertNotContains(detail, 'Write a Review')

        self.past_booking.status = 'CONFIRMED'
        self.past_booking.save(update_fields=['status'])
        Review.objects.create(user=self.user1, movie=self.movie, booking=self.past_booking, rating=3, review_text='Original')
        duplicate = self.client.post(url, {'rating': '1', 'review_text': 'Duplicate'}, **headers)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(Review.objects.filter(movie=self.movie, user=self.user1).count(), 1)

    def test_reported_reviews_are_removed_from_public_rating_and_moderatable(self):
        review = Review.objects.create(
            user=self.user1, movie=self.movie, booking=self.past_booking,
            rating=5, review_text='A reported review.'
        )
        self.client.login(username='viewer_bob', password='password123')
        self.client.post(reverse('report_review', kwargs={'review_id': review.id}), {'reason': 'Abusive content'})
        review.refresh_from_db()
        self.assertTrue(review.is_reported)
        self.assertEqual(self.movie.get_review_count(), 0)
        self.assertIsNone(self.movie.get_average_user_rating())

        detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': self.movie.id}))
        self.assertNotContains(detail, 'A reported review.')

        staff = User.objects.create_superuser(username='review_moderator', password='password123', email='moderator@test.com')
        self.client.force_login(staff)
        reports_page = self.client.get(reverse('admin_reports'))
        self.assertEqual(reports_page.status_code, 200)
        self.assertContains(reports_page, 'A reported review.')
        self.assertContains(reports_page, 'Abusive content')
        self.client.post(reverse('admin_reports'), {'action': 'dismiss', 'report_id': review.reports.get().id})
        review.refresh_from_db()
        self.assertFalse(review.is_reported)
        self.assertEqual(review.report_count, 0)
        self.assertEqual(self.movie.get_review_count(), 1)

        self.client.force_login(self.user2)
        self.client.post(reverse('report_review', kwargs={'review_id': review.id}), {'reason': 'Second moderation pass'})
        self.client.force_login(staff)
        moderation_page = self.client.get(reverse('admin_reviews'))
        self.assertContains(moderation_page, 'A reported review.')
        self.assertContains(moderation_page, '5/5')
        self.client.post(reverse('admin_reviews'), {'action': 'approve', 'review_id': review.id})
        review.refresh_from_db()
        self.assertFalse(review.is_reported)
        self.assertEqual(review.report_count, 0)
        self.assertFalse(review.reports.exists())

    def test_recommendation_sections_use_active_catalog_movies(self):
        similar = Movie.objects.create(
            name='Action Dream', title='Action Dream', original_language='en',
            release_date=timezone.now().date() - timedelta(days=3), popularity=80,
            is_in_active_catalog=True,
        )
        similar.genres.add(self.genre_action)
        Movie.objects.create(
            name='Draft Blockbuster', title='Draft Blockbuster', original_language='en',
            release_date=timezone.now().date() - timedelta(days=2), popularity=999,
            status='DRAFT',
        )
        detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': self.movie.id}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Similar Movies')
        self.assertContains(detail, 'Trending Movies')
        self.assertContains(detail, 'Recently Released')
        self.assertContains(detail, 'Action Dream')
        self.assertNotContains(detail, 'Draft Blockbuster')

    def test_review_editing_and_deletion(self):
        """User can edit and delete their own review."""
        review = Review.objects.create(
            user=self.user1,
            movie=self.movie,
            booking=self.past_booking,
            rating=4,
            review_text='Original'
        )

        self.client.login(username='viewer_alice', password='password123')
        # Edit
        edit_url = reverse('edit_review', kwargs={'review_id': review.id})
        self.client.post(edit_url, {'rating': '5', 'review_text': 'Updated to 5 stars'})
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review_text, 'Updated to 5 stars')

        # Delete
        delete_url = reverse('delete_review', kwargs={'review_id': review.id})
        self.client.post(delete_url)
        self.assertFalse(Review.objects.filter(id=review.id).exists())

    def test_review_reporting_and_duplicate_prevention(self):
        """Users can report inappropriate reviews and cannot report repeatedly."""
        review = Review.objects.create(
            user=self.user1,
            movie=self.movie,
            booking=self.past_booking,
            rating=1,
            review_text='Inappropriate content here'
        )

        self.client.login(username='viewer_bob', password='password123')
        report_url = reverse('report_review', kwargs={'review_id': review.id})

        # First report
        self.client.post(report_url, {'reason': 'Contains spoilers'})
        review.refresh_from_db()
        self.assertTrue(review.is_reported)
        self.assertEqual(review.report_count, 1)

        # Second report attempt by same user
        self.client.post(report_url, {'reason': 'Spam again'})
        review.refresh_from_db()
        self.assertEqual(review.report_count, 1)  # Stays 1, no duplicate report

    def test_tmdb_trailer_and_certification_helpers(self):
        """Test TMDBService extracts secure youtube-nocookie trailers and age ratings."""
        tmdb = TMDBService(api_key='dummy_key')

        videos_payload = {
            'results': [
                {'site': 'Vimeo', 'key': '123', 'type': 'Trailer'},
                {'site': 'YouTube', 'key': 'TeaserKey', 'type': 'Teaser', 'official': False},
                {'site': 'YouTube', 'key': 'OfficialTrailerKey', 'type': 'Trailer', 'official': True},
            ]
        }
        trailer_url = tmdb.extract_youtube_trailer_url(videos_payload)
        self.assertEqual(trailer_url, 'https://www.youtube-nocookie.com/embed/OfficialTrailerKey')

        release_dates_payload = {
            'results': [
                {'iso_3166_1': 'US', 'release_dates': [{'certification': 'PG-13'}]},
                {'iso_3166_1': 'IN', 'release_dates': [{'certification': 'UA'}]},
            ]
        }
        cert = tmdb.extract_age_certification(release_dates_payload)
        self.assertEqual(cert, 'UA')

    def test_trailer_url_safety_and_arbitrary_url_rejection(self):
        """Test YouTube trailers embed safely and arbitrary unsafe URLs are rejected."""
        # 1. Valid YouTube watch URL generates safe embed URL
        self.movie.trailer_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        self.movie.save()
        self.assertEqual(self.movie.get_trailer_embed_url(), 'https://www.youtube.com/embed/dQw4w9WgXcQ?enablejsapi=1&rel=0')
        self.assertEqual(self.movie.get_youtube_watch_url(), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

        # 2. Arbitrary/unsafe URLs return None to prevent unsafe iframe embedding
        self.movie.trailer_url = 'javascript:alert(1)'
        self.movie.save()
        self.assertIsNone(self.movie.get_trailer_embed_url())
        self.assertIsNone(self.movie.get_youtube_watch_url())

        self.movie.trailer_url = 'https://evil-phishing-site.example.com/exploit'
        self.movie.save()
        self.assertIsNone(self.movie.get_trailer_embed_url())
        self.assertIsNone(self.movie.get_youtube_watch_url())

        self.movie.trailer_url = 'https://evil-phishing-site.example.com/embed/dQw4w9WgXcQ'
        self.movie.save()
        self.assertIsNone(self.movie.get_trailer_embed_url())
        self.assertIsNone(self.movie.get_youtube_watch_url())

        # 3. Staff update_trailer view rejects arbitrary/unsafe URLs
        User.objects.create_user(username='trailer_admin', password='password123', is_staff=True)
        self.client.login(username='trailer_admin', password='password123')
        update_url = reverse('update_trailer', kwargs={'movie_id': self.movie.id})

        # Submit unsafe URL -> Rejected
        res = self.client.post(update_url, {'trailer_url': 'javascript:alert("hacked")'}, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Invalid YouTube URL')
        self.movie.refresh_from_db()
        self.assertNotEqual(self.movie.trailer_url, 'javascript:alert("hacked")')

        # Submit valid YouTube URL -> Accepted
        res2 = self.client.post(update_url, {'trailer_url': 'https://youtu.be/YoHD9XEInc0'}, follow=True)
        self.assertEqual(res2.status_code, 200)
        self.movie.refresh_from_db()
        self.assertIn('YoHD9XEInc0', self.movie.trailer_url)

    def test_movie_search_and_filters(self):
        """Test multi-attribute search and filtering in movie_list view."""
        # Search by cast
        res = self.client.get(reverse('movie_list'), {'search': 'Leonardo'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Inception')

        # Filter by genre
        res2 = self.client.get(reverse('movie_list'), {'genre': self.genre_action.id})
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, 'Inception')

        # Filter by minimum rating
        res3 = self.client.get(reverse('movie_list'), {'rating': '8'})
        self.assertEqual(res3.status_code, 200)
        self.assertContains(res3, 'Inception')

    def test_existing_booking_flow_preserved(self):
        """Test seat booking view works as expected with reservation and payment confirmation."""
        self.client.login(username='viewer_alice', password='password123')
        book_url = reverse('book_seats', kwargs={'theater_id': self.future_theater.id})

        # Booking the open seat B2 redirects to checkout
        response = self.client.post(book_url, {'seats': [str(self.open_seat.id)]}, follow=True)
        self.assertEqual(response.status_code, 200)

        # Confirm payment on created reservation
        res = SeatReservation.objects.get(user=self.user1, theater=self.future_theater, status='ACTIVE')
        confirm_url = reverse('confirm_payment', kwargs={'reservation_id': res.id})
        pay_res = self.client.post(confirm_url, follow=True)
        self.assertEqual(pay_res.status_code, 200)

        self.open_seat.refresh_from_db()
        self.assertTrue(self.open_seat.is_booked)
        self.assertTrue(Booking.objects.filter(seat=self.open_seat, user=self.user1).exists())
        res.refresh_from_db()
        self.assertEqual(res.status, 'CONVERTED')

    def test_movie_detail_view(self):
        """Test movie detail renders all components properly."""
        res = self.client.get(reverse('movie_detail', kwargs={'movie_id': self.movie.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Inception')
        self.assertContains(res, 'Leonardo DiCaprio')
        self.assertContains(res, 'PVR Koramangala')
        self.assertContains(res, 'Watch Trailer')
        self.assertContains(res, 'TMDB Rating')

    def test_import_tmdb_movies_command(self):
        """Test import_tmdb_movies command creates and updates movies idempotently."""
        from django.core.management import call_command
        fake_results = [{
            'id': 88888,
            'title': 'Test TMDB Movie',
            'overview': 'Great overview text',
            'release_date': '2024-01-15',
            'vote_average': 7.9,
            'vote_count': 500,
            'popularity': 65.0,
            'original_language': 'en',
            'poster_path': '/poster.jpg',
            'backdrop_path': '/backdrop.jpg',
        }]
        fake_detail = {
            **fake_results[0],
            'runtime': 125,
            'genres': [{'id': 28, 'name': 'Action'}],
            'spoken_languages': [{'iso_639_1': 'en', 'name': 'English'}],
            'credits': {'cast': [{'name': 'Actor Sample', 'character': 'Lead'}]},
            'videos': {'results': [{'site': 'YouTube', 'key': 'abc1234', 'type': 'Trailer', 'official': True}]},
            'release_dates': {'results': [{'iso_3166_1': 'IN', 'release_dates': [{'certification': 'UA'}]}]},
            'images': {'posters': [{'file_path': '/poster1.jpg'}]}
        }

        with patch('movies.services.tmdb_service.TMDBService.get_popular_movies', return_value={'results': fake_results}), \
             patch('movies.services.tmdb_service.TMDBService.get_movie_details', return_value=fake_detail), \
             patch.object(TMDBService, '__init__', lambda self, *a, **kw: setattr(self, 'api_key', 'test_key') or setattr(self, 'base_url', 'https://api.themoviedb.org/3') or setattr(self, 'image_base_url', 'https://image.tmdb.org/t/p/') or setattr(self, 'poster_size', 'w500') or setattr(self, 'backdrop_size', 'original') or setattr(self, 'profile_size', 'w185')):
            # First run: should create
            call_command('import_tmdb_movies', popular=True, pages=1)
            self.assertEqual(Movie.objects.filter(tmdb_id=88888).count(), 1)
            m = Movie.objects.get(tmdb_id=88888)
            self.assertEqual(m.title, 'Test TMDB Movie')
            self.assertEqual(m.runtime, 125)
            self.assertEqual(m.age_certification, 'UA')
            self.assertTrue('abc1234' in (m.trailer_url or ''))

            # Second run: should update without creating duplicate
            call_command('import_tmdb_movies', popular=True, pages=1)
            self.assertEqual(Movie.objects.filter(tmdb_id=88888).count(), 1)

    def test_reserve_seats_api(self):
        """Test atomic multi-seat reservation with 2-minute countdown timer."""
        # Create an extra seat
        seat_b3 = Seat.objects.create(theater=self.future_theater, seat_number='B3', is_booked=False)

        self.client.login(username='viewer_alice', password='password123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.future_theater.id})

        # Reserve B2 and B3
        res = self.client.post(reserve_url, json.dumps({'seats': [self.open_seat.id, seat_b3.id]}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn('reservation_id', data)
        self.assertTrue(118 <= data['seconds_left'] <= 120)

        # Verify reservation in DB
        reservation = SeatReservation.objects.get(id=data['reservation_id'])
        self.assertEqual(reservation.status, 'ACTIVE')
        self.assertEqual(reservation.seats.count(), 2)
        self.assertTrue(reservation.is_active())

    def test_concurrent_reservation_prevent_duplicate_hold(self):
        """User A holds a seat. User B attempting to hold the same seat is rejected."""
        self.client.login(username='viewer_alice', password='password123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.future_theater.id})

        # User A reserves open seat B2
        res1 = self.client.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')
        self.assertEqual(res1.status_code, 200)

        # User B attempts to reserve B2 simultaneously
        client2 = Client()
        client2.login(username='viewer_bob', password='password123')
        res2 = client2.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')
        self.assertEqual(res2.status_code, 409)
        self.assertFalse(res2.json()['success'])
        self.assertIn('no longer available', res2.json()['error'])

    def test_all_or_nothing_multi_seat_reservation(self):
        """If any of the selected seats is unavailable, no seats are reserved."""
        # Create free seat B3
        seat_b3 = Seat.objects.create(theater=self.future_theater, seat_number='B3', is_booked=False)

        # User A holds open seat B2
        self.client.login(username='viewer_alice', password='password123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.future_theater.id})
        self.client.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')

        # User B attempts to reserve B2 and B3 together
        client2 = Client()
        client2.login(username='viewer_bob', password='password123')
        res = client2.post(reserve_url, json.dumps({'seats': [self.open_seat.id, seat_b3.id]}), content_type='application/json')
        self.assertEqual(res.status_code, 409)

        # B3 must NOT be held by User B
        self.assertFalse(SeatReservation.objects.filter(user=self.user2, seats=seat_b3, status='ACTIVE').exists())

    def test_seat_modification_preserves_timer(self):
        """Modifying seat selection updates held seats while preserving the original expiry timer."""
        seat_b3 = Seat.objects.create(theater=self.future_theater, seat_number='B3', is_booked=False)

        self.client.login(username='viewer_alice', password='password123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.future_theater.id})

        # Initial hold B2
        res1 = self.client.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')
        res_id = res1.json()['reservation_id']
        res_obj = SeatReservation.objects.get(id=res_id)
        original_expires_at = res_obj.expires_at

        # Modify to hold B3 instead
        res2 = self.client.post(reserve_url, json.dumps({'seats': [seat_b3.id]}), content_type='application/json')
        self.assertEqual(res2.status_code, 200)

        res_obj.refresh_from_db()
        self.assertEqual(res_obj.expires_at, original_expires_at)
        self.assertEqual(list(res_obj.seats.values_list('id', flat=True)), [seat_b3.id])

        # B2 should now be released and available to other users
        client2 = Client()
        client2.login(username='viewer_bob', password='password123')
        res_b = client2.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')
        self.assertEqual(res_b.status_code, 200)

    def test_live_seat_status_polling_endpoint(self):
        """Endpoint /theater/<id>/seats/status/ accurately reports available, selected, reserved, booked."""
        seat_b3 = Seat.objects.create(theater=self.future_theater, seat_number='B3', is_booked=False)

        # User A holds open seat B2
        self.client.login(username='viewer_alice', password='password123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.future_theater.id})
        self.client.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')

        status_url = reverse('seat_status', kwargs={'theater_id': self.future_theater.id})

        # From User A's perspective:
        res_a = self.client.get(status_url)
        data_a = res_a.json()['seats']
        self.assertEqual(data_a[str(self.future_seat.id)]['status'], 'booked')
        self.assertEqual(data_a[str(self.open_seat.id)]['status'], 'selected')
        self.assertEqual(data_a[str(seat_b3.id)]['status'], 'available')

        # From User B's perspective:
        client2 = Client()
        client2.login(username='viewer_bob', password='password123')
        res_b = client2.get(status_url)
        data_b = res_b.json()['seats']
        self.assertEqual(data_b[str(self.open_seat.id)]['status'], 'reserved')
        self.assertEqual(data_b[str(seat_b3.id)]['status'], 'available')

    def test_expired_reservation_cleanup(self):
        """Expired reservations are automatically treated as available and release_expired_reservations updates them."""
        # Create an expired reservation for open seat B2
        res = SeatReservation.objects.create(
            user=self.user1,
            theater=self.future_theater,
            expires_at=timezone.now() - timedelta(seconds=10),
            status='ACTIVE'
        )
        res.seats.add(self.open_seat)

        # User B should be able to reserve it immediately because it's expired
        client2 = Client()
        client2.login(username='viewer_bob', password='password123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.future_theater.id})
        res2 = client2.post(reserve_url, json.dumps({'seats': [self.open_seat.id]}), content_type='application/json')
        self.assertEqual(res2.status_code, 200)

        # Running management command updates status
        from django.core.management import call_command
        call_command('release_expired_reservations')
        res.refresh_from_db()
        self.assertEqual(res.status, 'EXPIRED')

    def test_unauthorized_checkout_blocked(self):
        """User B cannot view or confirm payment for User A's reservation."""
        res = SeatReservation.objects.create(
            user=self.user1,
            theater=self.future_theater,
            expires_at=timezone.now() + timedelta(minutes=2),
            status='ACTIVE'
        )
        res.seats.add(self.open_seat)

        client2 = Client()
        client2.login(username='viewer_bob', password='password123')

        checkout_url = reverse('checkout', kwargs={'reservation_id': res.id})
        response = client2.get(checkout_url)
        self.assertEqual(response.status_code, 302)  # Redirects unauthorized user


class SmartSeatReservationTask2Tests(TestCase):
    """
    Dedicated comprehensive test suite verifying all 15 Task 2 functional requirements.
    """
    def setUp(self):
        self.client_alice = Client()
        self.client_bob = Client()
        self.user_alice = User.objects.create_user(username='alice_mitra', password='password123')
        self.user_bob = User.objects.create_user(username='bob_mitra', password='password123')
        self.client_alice.login(username='alice_mitra', password='password123')
        self.client_bob.login(username='bob_mitra', password='password123')

        self.movie = Movie.objects.create(
            name='Interstellar',
            title='Interstellar',
            tmdb_id=157336,
            rating=8.6,
            release_date=timezone.now().date(),
            runtime=169
        )
        self.theater = Theater.objects.create(
            name='IMAX 70mm Screen 1',
            movie=self.movie,
            time=timezone.now() + timedelta(days=2)
        )

        # Create seats: A1, A2, A3, A4
        self.seat_a1 = Seat.objects.create(theater=self.theater, seat_number='A1', is_booked=False)
        self.seat_a2 = Seat.objects.create(theater=self.theater, seat_number='A2', is_booked=False)
        self.seat_a3 = Seat.objects.create(theater=self.theater, seat_number='A3', is_booked=False)
        self.seat_a4 = Seat.objects.create(theater=self.theater, seat_number='A4', is_booked=False)

        # Existing confirmed booking for A4
        self.seat_a4.is_booked = True
        self.seat_a4.save()
        self.booked_user = User.objects.create_user(username='charlie_booked', password='password123')
        self.booking_a4 = Booking.objects.create(
            user=self.booked_user,
            seat=self.seat_a4,
            movie=self.movie,
            theater=self.theater
        )

        self.reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.theater.id})
        self.update_url = reverse('update_reservation', kwargs={'theater_id': self.theater.id})
        self.cancel_url = reverse('cancel_reservation', kwargs={'theater_id': self.theater.id})
        self.status_url = reverse('seat_status', kwargs={'theater_id': self.theater.id})
        self.book_seats_url = reverse('book_seats', kwargs={'theater_id': self.theater.id})

    def test_1_user_can_reserve_one_seat(self):
        """1. User can reserve one seat."""
        res = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn('reservation_id', data)
        self.assertEqual(data['seat_numbers'], ['A1'])
        self.assertTrue(118 <= data['seconds_left'] <= 120)

        reservation = SeatReservation.objects.get(id=data['reservation_id'])
        self.assertEqual(reservation.status, 'ACTIVE')
        self.assertEqual(list(reservation.seats.all()), [self.seat_a1])

    def test_2_user_can_reserve_multiple_seats(self):
        """2. User can reserve multiple seats atomically."""
        res = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id, self.seat_a2.id, self.seat_a3.id]}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['seat_numbers']), 3)
        self.assertEqual(data['total_amount'], 540.00)

        reservation = SeatReservation.objects.get(id=data['reservation_id'])
        self.assertEqual(reservation.seats.count(), 3)

    def test_3_user_cannot_reserve_booked_seat(self):
        """3. User cannot reserve a booked seat."""
        res = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a4.id]}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 409)
        self.assertFalse(res.json()['success'])
        self.assertIn('already booked', res.json()['error'].lower())

    def test_4_user_cannot_reserve_another_user_active_reservation(self):
        """4. User cannot reserve another user's active reservation."""
        # Alice reserves A1
        self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )

        # Bob attempts to reserve A1
        res = self.client_bob.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 409)
        self.assertFalse(res.json()['success'])
        self.assertIn('no longer available', res.json()['error'])

    def test_5_reservation_expires_after_2_minutes(self):
        """5. Reservation expires exactly after 2 minutes."""
        res = SeatReservation.objects.create(
            user=self.user_alice,
            theater=self.theater,
            expires_at=timezone.now() + timedelta(minutes=2),
            status='ACTIVE'
        )
        res.seats.add(self.seat_a1)

        self.assertTrue(res.is_active())
        self.assertTrue(res.time_remaining_seconds() > 0)

        # Advance expiration to past
        res.expires_at = timezone.now() - timedelta(seconds=1)
        res.save()

        self.assertFalse(res.is_active())
        self.assertEqual(res.time_remaining_seconds(), 0)

    def test_6_expired_seat_becomes_available(self):
        """6. Expired reservation does not block seats and becomes available."""
        # Alice's expired reservation
        res = SeatReservation.objects.create(
            user=self.user_alice,
            theater=self.theater,
            expires_at=timezone.now() - timedelta(seconds=10),
            status='ACTIVE'
        )
        res.seats.add(self.seat_a1)

        # Bob can successfully reserve A1 now
        res_bob = self.client_bob.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        self.assertEqual(res_bob.status_code, 200)
        self.assertTrue(res_bob.json()['success'])

    def test_7_user_can_remove_a_seat(self):
        """7. User can remove a seat from their active reservation."""
        # Alice reserves A1 and A2
        self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id, self.seat_a2.id]}),
            content_type='application/json'
        )

        # Alice updates to keep only A1
        res = self.client_alice.post(
            self.update_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)

        # Bob can immediately reserve A2
        res_bob = self.client_bob.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a2.id]}),
            content_type='application/json'
        )
        self.assertEqual(res_bob.status_code, 200)
        self.assertTrue(res_bob.json()['success'])

    def test_8_user_can_add_a_seat(self):
        """8. User can add a seat while preserving the countdown timer."""
        # Alice reserves A1
        res1 = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        res_id = res1.json()['reservation_id']
        reservation = SeatReservation.objects.get(id=res_id)
        original_expires_at = reservation.expires_at

        # Alice adds A2 via update
        res2 = self.client_alice.post(
            self.update_url,
            json.dumps({'seats': [self.seat_a1.id, self.seat_a2.id]}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 200)

        reservation.refresh_from_db()
        self.assertEqual(reservation.seats.count(), 2)
        # Timer MUST NOT be reset
        self.assertEqual(reservation.expires_at, original_expires_at)

    def test_9_user_can_cancel_reservation(self):
        """9. User can cancel reservation and seats become available."""
        # Alice reserves A1
        self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )

        # Alice cancels reservation
        res_cancel = self.client_alice.post(
            self.cancel_url,
            json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(res_cancel.status_code, 200)
        self.assertTrue(res_cancel.json()['success'])

        reservation = SeatReservation.objects.get(user=self.user_alice, theater=self.theater)
        self.assertEqual(reservation.status, 'CANCELLED')
        self.assertEqual(reservation.seats.count(), 0)

        # Bob can now reserve A1
        res_bob = self.client_bob.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        self.assertEqual(res_bob.status_code, 200)

    def test_10_timer_survives_page_refresh(self):
        """10. Timer survives page refresh and calculates from expires_at."""
        # Alice reserves A1
        res_create = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        res_id = res_create.json()['reservation_id']
        reservation = SeatReservation.objects.get(id=res_id)

        # Simulate 40 seconds passed
        reservation.expires_at = timezone.now() + timedelta(seconds=80)
        reservation.save()

        # Alice refreshes the seat selection page (GET)
        res_page = self.client_alice.get(self.book_seats_url)
        self.assertEqual(res_page.status_code, 200)
        self.assertContains(res_page, 'seat-selected')

        # Poll status
        res_status = self.client_alice.get(self.status_url)
        user_res_data = res_status.json()['user_reservation']
        self.assertIsNotNone(user_res_data)
        self.assertTrue(78 <= user_res_data['seconds_left'] <= 80)

    def test_11_reservation_does_not_partially_succeed(self):
        """11. Reservation does not partially succeed if any seat is unavailable (all-or-nothing)."""
        # Alice reserves A1
        self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )

        # Bob attempts to reserve A1 and A2 together
        res_bob = self.client_bob.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id, self.seat_a2.id]}),
            content_type='application/json'
        )
        self.assertEqual(res_bob.status_code, 409)

        # A2 must NOT be reserved by Bob
        self.assertFalse(SeatReservation.objects.filter(user=self.user_bob, seats=self.seat_a2, status='ACTIVE').exists())

    def test_12_existing_bookings_remain_valid(self):
        """12. Existing confirmed bookings remain valid and appear as booked."""
        # Seat A4 is already booked by charlie
        res_status = self.client_alice.get(self.status_url)
        data = res_status.json()['seats']
        self.assertEqual(data[str(self.seat_a4.id)]['status'], 'booked')

        # Attempt to book A4 must fail
        res = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a4.id]}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 409)

    def test_13_live_availability_endpoint_works(self):
        """13. Live availability endpoint returns correct states without leaking user info."""
        # Alice reserves A1
        self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )

        # Status for Bob
        res = self.client_bob.get(self.status_url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        seats = data['seats']

        self.assertEqual(seats[str(self.seat_a1.id)]['status'], 'reserved')
        self.assertEqual(seats[str(self.seat_a2.id)]['status'], 'available')
        self.assertEqual(seats[str(self.seat_a4.id)]['status'], 'booked')

        # Verify no username leak in seats map
        raw_content = res.content.decode('utf-8')
        self.assertNotIn('alice_mitra', raw_content)

    def test_14_unauthorized_user_cannot_modify_another_reservation(self):
        """14. Unauthorized user cannot modify or cancel another user's reservation."""
        # Alice reserves A1
        res1 = self.client_alice.post(
            self.reserve_url,
            json.dumps({'seats': [self.seat_a1.id]}),
            content_type='application/json'
        )
        alice_res_id = res1.json()['reservation_id']

        # Bob attempts to update reservation for theater (he has no active reservation)
        res_bob_update = self.client_bob.post(
            self.update_url,
            json.dumps({'seats': [self.seat_a2.id]}),
            content_type='application/json'
        )
        self.assertEqual(res_bob_update.status_code, 410)

        # Bob attempts to cancel reservation
        res_bob_cancel = self.client_bob.post(
            self.cancel_url,
            json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(res_bob_cancel.status_code, 200)

        # Alice's reservation must remain ACTIVE and untouched
        alice_res = SeatReservation.objects.get(id=alice_res_id)
        self.assertEqual(alice_res.status, 'ACTIVE')
        self.assertEqual(list(alice_res.seats.all()), [self.seat_a1])

    def test_15_checkout_cannot_continue_after_reservation_expiration(self):
        """15. Checkout cannot continue after reservation expiration."""
        # Alice creates reservation that is already expired
        res = SeatReservation.objects.create(
            user=self.user_alice,
            theater=self.theater,
            expires_at=timezone.now() - timedelta(seconds=1),
            status='ACTIVE'
        )
        res.seats.add(self.seat_a1)

        # Accessing checkout redirects back to book_seats
        checkout_url = reverse('checkout', kwargs={'reservation_id': res.id})
        res_checkout = self.client_alice.get(checkout_url)
        self.assertEqual(res_checkout.status_code, 302)
        checkout_redirect = res_checkout.headers.get('Location') or getattr(res_checkout, 'url', '')
        self.assertIn(f'/movies/theater/{self.theater.id}/seats/book/', checkout_redirect)

        # Attempting to confirm payment rejects
        confirm_url = reverse('confirm_payment', kwargs={'reservation_id': res.id})
        res_confirm = self.client_alice.post(confirm_url)
        self.assertEqual(res_confirm.status_code, 302)
        self.assertFalse(Booking.objects.filter(seat=self.seat_a1).exists())


class SmartSeatReservationConcurrencyTests(TransactionTestCase):
    """
    Concurrency test verifying atomic transaction locking and race condition protection.
    """
    def setUp(self):
        self.user_a = User.objects.create_user(username='concur_user_a', password='password123')
        self.user_b = User.objects.create_user(username='concur_user_b', password='password123')
        self.movie = Movie.objects.create(name='Concurrency Movie', title='Concurrency Movie', tmdb_id=99999)
        self.theater = Theater.objects.create(name='Screen Concurrency', movie=self.movie, time=timezone.now() + timedelta(days=1))
        self.seat_c1 = Seat.objects.create(theater=self.theater, seat_number='C1', is_booked=False)
        self.reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.theater.id})

    def test_16_concurrency_simultaneous_reservation_attempts(self):
        """
        User A and User B simultaneously attempt to reserve seat C1.
        Only ONE user must succeed (status 200), and the other must be rejected (status 409).
        """
        import threading

        from django.db import connections

        client_a = Client()
        client_b = Client()
        client_a.login(username='concur_user_a', password='password123')
        client_b.login(username='concur_user_b', password='password123')

        results = []
        barrier = threading.Barrier(2)

        def attempt_reserve(client, username):
            connections.close_all()
            try:
                barrier.wait(timeout=5)
            except Exception:
                pass
            res = client.post(self.reserve_url, json.dumps({'seats': [self.seat_c1.id]}), content_type='application/json')
            results.append((username, res.status_code))
            connections.close_all()

        t1 = threading.Thread(target=attempt_reserve, args=(client_a, 'concur_user_a'))
        t2 = threading.Thread(target=attempt_reserve, args=(client_b, 'concur_user_b'))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        status_codes = sorted([r[1] for r in results])
        self.assertEqual(len(status_codes), 2)
        # Exactly one 200 (success) and one 409 (conflict/rejection)
        self.assertEqual(status_codes, [200, 409])

        # Exactly one active reservation exists for seat C1
        active_res = SeatReservation.objects.filter(theater=self.theater, seats=self.seat_c1, status='ACTIVE')
        self.assertEqual(active_res.count(), 1)


class PaymentWorkflowTask3Tests(TestCase):
    """
    Dedicated test suite for Task 3: Razorpay Standard Web Checkout,
    server-side order creation, HMAC signature verification, atomic booking
    confirmation, duplicate-payment protection, and webhook handling.
    """
    def setUp(self):
        self.client_alice = Client()
        self.client_bob = Client()
        self.user_alice = User.objects.create_user(username='alice_pay', password='password123', email='alice@pay.com')
        self.user_bob = User.objects.create_user(username='bob_pay', password='password123', email='bob@pay.com')
        self.client_alice.login(username='alice_pay', password='password123')
        self.client_bob.login(username='bob_pay', password='password123')

        self.movie = Movie.objects.create(
            name='K.G.F: Chapter 2',
            title='K.G.F: Chapter 2',
            tmdb_id=87001,
            original_language='kn'
        )
        self.theater = Theater.objects.create(
            name='PVR Gold Screen 1',
            movie=self.movie,
            time=timezone.now() + timedelta(days=2)
        )
        self.seat_1 = Seat.objects.create(theater=self.theater, seat_number='P1', is_booked=False)
        self.seat_2 = Seat.objects.create(theater=self.theater, seat_number='P2', is_booked=False)

        # Create active 2-minute reservation for Alice
        self.reservation = SeatReservation.objects.create(
            user=self.user_alice,
            theater=self.theater,
            expires_at=timezone.now() + timedelta(minutes=2),
            status='ACTIVE',
            total_amount=300.00
        )
        self.reservation.seats.set([self.seat_1, self.seat_2])

    def generate_valid_signature(self, order_id, payment_id):
        from django.conf import settings
        msg = f"{order_id}|{payment_id}".encode()
        secret = getattr(settings, 'STRIPE_SECRET_KEY', 'test_secret')
        return hmac.new(secret.encode('utf-8'), msg, 'sha256').hexdigest()

    def test_01_create_order_server_side_amount(self):
        """Order creation calculates amount server-side and stores Payment with CREATED status."""
        url = reverse('create_payment_order', kwargs={'reservation_id': self.reservation.id})
        with patch('movies.services.stripe_service.create_payment_intent') as mock_create:
            mock_create.return_value = {
                'id': 'order_test_12345',
                'amount': 30000,
                'currency': 'INR'
            }
            res = self.client_alice.post(url)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data['success'])
            self.assertEqual(data['order_id'], 'order_test_12345')
            self.assertEqual(data['amount'], 30000)

            # Check Payment record in DB
            payment = Payment.objects.get(order_id='order_test_12345')
            self.assertEqual(payment.user, self.user_alice)
            self.assertEqual(payment.status, 'CREATED')
            self.assertEqual(payment.amount, 300.00)

    def test_02_create_order_expired_reservation_rejected(self):
        """Expired reservation cannot generate a payment order."""
        self.reservation.expires_at = timezone.now() - timedelta(seconds=10)
        self.reservation.save()

        url = reverse('create_payment_order', kwargs={'reservation_id': self.reservation.id})
        res = self.client_alice.post(url)
        self.assertEqual(res.status_code, 410)
        data = res.json()
        self.assertFalse(data['success'])
        self.assertTrue(data.get('expired'))

    def test_03_create_order_unauthorized_user_rejected(self):
        """User Bob cannot create an order for User Alice's reservation."""
        url = reverse('create_payment_order', kwargs={'reservation_id': self.reservation.id})
        res = self.client_bob.post(url)
        self.assertEqual(res.status_code, 403)

    def test_04_create_order_already_booked_seat_rejected(self):
        """If a seat was already booked, order creation is rejected with 409."""
        self.seat_1.is_booked = True
        self.seat_1.save()

        url = reverse('create_payment_order', kwargs={'reservation_id': self.reservation.id})
        res = self.client_alice.post(url)
        self.assertEqual(res.status_code, 409)

    def test_05_verify_payment_valid_signature_confirms_booking(self):
        """Valid payment signature confirms bookings and converts reservation atomically."""
        order_id = 'pi_test_succ_1'
        payment_id = 'pi_test_succ_1'
        sig = self.generate_valid_signature(order_id, payment_id)

        Payment.objects.create(
            user=self.user_alice,
            reservation=self.reservation,
            amount=300.00,
            order_id=order_id,
            status='CREATED'
        )

        url = reverse('verify_payment', kwargs={'reservation_id': self.reservation.id})
        payload = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig
        }
        with patch('movies.services.stripe_service.retrieve_payment_intent', return_value=SimpleNamespace(id=payment_id, status='succeeded', amount=30000, currency='inr')):
            res = self.client_alice.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])

        # Verify DB updates
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CONVERTED')

        self.seat_1.refresh_from_db()
        self.seat_2.refresh_from_db()
        self.assertTrue(self.seat_1.is_booked)
        self.assertTrue(self.seat_2.is_booked)

        payment = Payment.objects.get(order_id=order_id)
        self.assertEqual(payment.status, 'SUCCESS')
        self.assertEqual(payment.payment_id, payment_id)
        self.assertEqual(payment.bookings.count(), 2)

    def test_06_verify_payment_invalid_signature_rejected(self):
        """Invalid signature returns 400 and marks payment FAILED without booking."""
        order_id = 'order_test_fail_1'
        payment_id = 'pay_test_fail_1'
        invalid_sig = 'bad_forged_signature_12345'

        Payment.objects.create(
            user=self.user_alice,
            reservation=self.reservation,
            amount=300.00,
            order_id=order_id,
            status='CREATED'
        )

        url = reverse('verify_payment', kwargs={'reservation_id': self.reservation.id})
        payload = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': invalid_sig
        }
        res = self.client_alice.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)

        # Seats remain unbooked
        self.seat_1.refresh_from_db()
        self.assertFalse(self.seat_1.is_booked)

        payment = Payment.objects.get(order_id=order_id)
        self.assertEqual(payment.status, 'FAILED')

    def test_07_verify_payment_missing_params_rejected(self):
        """Missing verification parameters return 400."""
        url = reverse('verify_payment', kwargs={'reservation_id': self.reservation.id})
        res = self.client_alice.post(url, json.dumps({'razorpay_order_id': 'xyz'}), content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_08_duplicate_payment_idempotency_protection(self):
        """Repeated verification calls return the same booking and never duplicate records."""
        order_id = 'pi_idempotent_1'
        payment_id = 'pi_idempotent_1'
        sig = self.generate_valid_signature(order_id, payment_id)

        Payment.objects.create(
            user=self.user_alice,
            reservation=self.reservation,
            amount=300.00,
            order_id=order_id,
            status='CREATED'
        )

        url = reverse('verify_payment', kwargs={'reservation_id': self.reservation.id})
        payload = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig
        }

        # First Call
        verified_intent = SimpleNamespace(id=payment_id, status='succeeded', amount=30000, currency='inr')
        with patch('movies.services.stripe_service.retrieve_payment_intent', return_value=verified_intent):
            res1 = self.client_alice.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(res1.status_code, 200)

        booking_count_1 = Booking.objects.filter(theater=self.theater, user=self.user_alice).count()
        self.assertEqual(booking_count_1, 2)

        # Duplicate Call
        with patch('movies.services.stripe_service.retrieve_payment_intent', return_value=verified_intent):
            res2 = self.client_alice.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2.get('already_confirmed') or data2.get('success'))

        # Booking count remains exactly 2 (zero duplicates)
        booking_count_2 = Booking.objects.filter(theater=self.theater, user=self.user_alice).count()
        self.assertEqual(booking_count_2, 2)

    def test_09_payment_failure_cancels_reservation(self):
        """Payment cancellation releases the reserved seats."""
        url = reverse('payment_failure', kwargs={'reservation_id': self.reservation.id})
        payload = {
            'order_id': 'order_cancel_1',
            'action': 'cancelled',
            'reason': 'User closed modal'
        }
        res = self.client_alice.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)

        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CANCELLED')
        self.assertEqual(self.reservation.seats.count(), 0)

    def test_10_webhook_payment_captured(self):
        """Signed Stripe webhook converts reservation and books seats."""
        order_id = 'pi_webhook_1'
        payment_id = 'pi_webhook_1'

        Payment.objects.create(
            user=self.user_alice,
            reservation=self.reservation,
            amount=300.00,
            order_id=order_id,
            status='CREATED'
        )

        payload = {'type': 'payment_intent.succeeded', 'data': {'object': {'id': payment_id, 'amount': 30000, 'currency': 'inr', 'status': 'succeeded'}}}
        body_bytes = json.dumps(payload).encode('utf-8')
        secret = 'whsec_test_ticketmitra'
        timestamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), f'{timestamp}.'.encode() + body_bytes, hashlib.sha256).hexdigest()
        sig = f't={timestamp},v1={digest}'
        url = reverse('stripe_webhook')
        with override_settings(STRIPE_WEBHOOK_SECRET=secret):
            res = self.client.post(url, body_bytes, content_type='application/json', HTTP_STRIPE_SIGNATURE=sig)
        self.assertEqual(res.status_code, 200)

        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CONVERTED')

        payment = Payment.objects.get(order_id=order_id)
        self.assertEqual(payment.status, 'SUCCESS')

    def test_11_webhook_invalid_signature_rejected(self):
        """Webhook with invalid signature is rejected with 400."""
        url = reverse('stripe_webhook')
        res = self.client.post(url, b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='bad_sig')
        self.assertEqual(res.status_code, 400)

    def test_12_generic_api_endpoints(self):
        """Generic endpoints /api/create-order and /api/verify-payment function correctly."""
        url_create = reverse('api_create_order')
        with patch('movies.services.stripe_service.create_payment_intent') as mock_c:
            mock_c.return_value = {'id': 'ord_api_1', 'amount': 15000, 'currency': 'INR'}
            res = self.client_alice.post(url_create, json.dumps({'reservation_id': self.reservation.id}), content_type='application/json')
            self.assertEqual(res.status_code, 200)

        url_verify = reverse('api_verify_payment')
        sig = self.generate_valid_signature('ord_api_1', 'pay_api_1')
        with patch('movies.services.stripe_service.verify_payment_signature', return_value=True):
            res_v = self.client_alice.post(url_verify, json.dumps({
                'razorpay_order_id': 'ord_api_1',
                'razorpay_payment_id': 'pay_api_1',
                'razorpay_signature': sig
            }), content_type='application/json')
            self.assertEqual(res_v.status_code, 200)

    def test_13_digital_ticket_view(self):
        """Digital ticket view renders confirmed details for ticket owner."""
        booking = Booking.objects.create(
            user=self.user_alice,
            theater=self.theater,
            movie=self.movie,
            seat=self.seat_1
        )
        url = reverse('booking_ticket', kwargs={'booking_id': booking.id})
        res = self.client_alice.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Booking Confirmed')
        self.assertContains(res, 'P1')

        # Bob cannot view Alice's ticket
        res_bob = self.client_bob.get(url)
        self.assertEqual(res_bob.status_code, 302)

    def test_14_my_bookings_and_payment_history_views(self):
        """My Bookings and Payment History views render successfully."""
        res_b = self.client_alice.get(reverse('my_bookings'))
        self.assertEqual(res_b.status_code, 200)

        res_p = self.client_alice.get(reverse('payment_history'))
        self.assertEqual(res_p.status_code, 200)


class MovieDiscoveryTests(TestCase):
    """
    Test suite for Task 5: Movie Discovery with Search, Filters, and Recommendations.
    """
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='discovery_user', password='password123')
        self.client.login(username='discovery_user', password='password123')

        # Genres & Languages
        self.genre_action, _ = Genre.objects.get_or_create(name='Action', defaults={'tmdb_id': 101})
        self.genre_drama, _ = Genre.objects.get_or_create(name='Drama', defaults={'tmdb_id': 102})
        self.lang_en, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
        self.lang_kn, _ = Language.objects.get_or_create(code='kn', defaults={'name': 'Kannada'})

        # Movies
        self.movie1 = Movie.objects.create(
            name='Avatar: Way of Water',
            title='Avatar: Way of Water',
            original_language='en',
            release_date=date(2025, 12, 1),
            rating=8.2,
            popularity=95.0,
        )
        self.movie1.genres.add(self.genre_action)
        self.movie1.languages.add(self.lang_en)

        self.movie2 = Movie.objects.create(
            name='Kantara Chapter 1',
            title='Kantara Chapter 1',
            original_language='kn',
            release_date=date(2026, 1, 15),
            rating=9.0,
            popularity=110.0,
        )
        self.movie2.genres.add(self.genre_action, self.genre_drama)
        self.movie2.languages.add(self.lang_kn)

        self.movie3 = Movie.objects.create(
            name='The Quiet Drama',
            title='The Quiet Drama',
            original_language='en',
            release_date=date(2024, 5, 20),
            rating=6.5,
            popularity=30.0,
        )
        self.movie3.genres.add(self.genre_drama)
        self.movie3.languages.add(self.lang_en)

        # Theaters with showtimes and prices
        now = timezone.now()
        self.theater1 = Theater.objects.create(
            name='PVR Koramangala',
            movie=self.movie1,
            time=now.replace(hour=9, minute=30, second=0),  # Morning
            city='Bengaluru',
            price=250.00,
            active=True
        )
        self.theater2 = Theater.objects.create(
            name='INOX Forum South',
            movie=self.movie2,
            time=now.replace(hour=18, minute=45, second=0),  # Evening
            city='Bengaluru',
            price=350.00,
            active=True
        )
        self.theater3 = Theater.objects.create(
            name='Cinepolis Mysuru',
            movie=self.movie3,
            time=now.replace(hour=14, minute=0, second=0),  # Afternoon
            city='Mysuru',
            price=150.00,
            active=True
        )

        # Seats
        self.seat1 = Seat.objects.create(theater=self.theater2, seat_number='A1', is_booked=True)

    def test_search_by_title(self):
        """Searching by movie title filters results accurately."""
        url = reverse('movie_list') + "?search=Avatar"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        found_ids = [m.id for m in res.context['page_obj']]
        self.assertIn(self.movie1.id, found_ids)
        self.assertNotIn(self.movie2.id, found_ids)

    def test_filter_by_genre_and_language(self):
        """Filtering by genre and language returns matching movies."""
        url = reverse('movie_list') + f"?genre={self.genre_action.id}&language=kn"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        found_ids = [m.id for m in res.context['page_obj']]
        self.assertIn(self.movie2.id, found_ids)
        self.assertNotIn(self.movie3.id, found_ids)

    def test_filter_by_city_and_theater(self):
        """Filtering by city and theater venues."""
        # City filter
        res_city = self.client.get(reverse('movie_list') + "?city=Mysuru")
        self.assertEqual(res_city.status_code, 200)
        found_city_ids = [m.id for m in res_city.context['page_obj']]
        self.assertIn(self.movie3.id, found_city_ids)
        self.assertNotIn(self.movie1.id, found_city_ids)

        # Theater filter
        res_th = self.client.get(reverse('movie_list') + f"?theater={self.theater2.id}")
        self.assertEqual(res_th.status_code, 200)
        found_th_ids = [m.id for m in res_th.context['page_obj']]
        self.assertIn(self.movie2.id, found_th_ids)
        self.assertNotIn(self.movie3.id, found_th_ids)

    def test_filter_by_show_timings(self):
        """Filtering by morning, afternoon, evening showtimes."""
        # Morning (<12) should match theater1 (movie1)
        res_m = self.client.get(reverse('movie_list') + "?timing=morning")
        self.assertEqual(res_m.status_code, 200)
        found_m_ids = [m.id for m in res_m.context['page_obj']]
        self.assertIn(self.movie1.id, found_m_ids)

        # Evening (16-20) should match theater2 (movie2)
        res_e = self.client.get(reverse('movie_list') + "?timing=evening")
        self.assertEqual(res_e.status_code, 200)
        found_e_ids = [m.id for m in res_e.context['page_obj']]
        self.assertIn(self.movie2.id, found_e_ids)

    def test_sorting_by_price_and_rating(self):
        """Sorting by ticket price and ratings."""
        # Price low to high: movie3 (150) should come before movie2 (350)
        res_p = self.client.get(reverse('movie_list') + "?sort=price_low")
        self.assertEqual(res_p.status_code, 200)
        movies = list(res_p.context['page_obj'])
        self.assertTrue(movies[0].min_ticket_price <= movies[-1].min_ticket_price)

        # Rating sort: movie2 (9.0) should come before movie3 (6.5)
        res_r = self.client.get(reverse('movie_list') + "?sort=rating")
        self.assertEqual(res_r.status_code, 200)
        movies_r = list(res_r.context['page_obj'])
        self.assertEqual(movies_r[0].id, self.movie2.id)

    def test_dynamic_count_and_ajax_response(self):
        """AJAX request dynamically returns match count and movie payload."""
        url = reverse('movie_list') + "?genre=Action&format=json"
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertGreaterEqual(data['count'], 2)
        self.assertTrue(any('Avatar' in m['title'] for m in data['results']))

    def test_pagination_and_query_preservation(self):
        """Pagination preserves filter parameters."""
        url = reverse('movie_list') + "?genre=Action&sort=rating"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn('preserved_query', res.context)
        self.assertIn('genre=Action', res.context['preserved_query'])

    def test_personalized_recommendations(self):
        """Recommendations reflect user booking history and viewed movies."""
        # Book Kantara (Kannada, Action)
        Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie2,
            theater=self.theater2,
            amount=350.00,
            status='CONFIRMED'
        )
        url = reverse('movie_list')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        recs = res.context['recommended_movies']
        # User already booked movie2, so movie2 should NOT be recommended
        rec_ids = [m.id for m in recs]
        self.assertNotIn(self.movie2.id, rec_ids)
        # Should recommend Avatar because it shares Action genre
        self.assertIn(self.movie1.id, rec_ids)


