from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from movies.models import (
    Booking,
    Movie,
    Payment,
    Screen,
    Seat,
    Theater,
)


class TicketMitraAdminOperationsTests(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Create Superuser, Staff user, and Normal user
        self.superuser = User.objects.create_superuser(
            username='admin_boss', email='admin@ticketmitra.com', password='adminpassword123'
        )
        self.staff_user = User.objects.create_user(
            username='staff_member', email='staff@ticketmitra.com', password='staffpassword123', is_staff=True
        )
        self.normal_user = User.objects.create_user(
            username='regular_customer', email='cust@gmail.com', password='custpassword123'
        )

        # 2. Create Movie, Screen, Theater
        self.movie = Movie.objects.create(
            name="Inception IMAX",
            title="Inception IMAX",
            rating=9.0,
            original_language="en",
            popularity=150.0
        )
        self.screen = Screen.objects.create(
            theater_name="INOX Galleria",
            name="Screen 1",
            screen_type="IMAX",
            capacity=30,
            active=True
        )
        self.theater = Theater.objects.create(
            name="INOX Galleria",
            movie=self.movie,
            screen=self.screen,
            time=timezone.now() + timedelta(hours=2),
            location="Bengaluru, Karnataka",
            city="Bengaluru",
            active=True
        )

        # 3. Create sample seats
        self.seat_a1 = Seat.objects.create(theater=self.theater, screen=self.screen, row="A", seat_number="A1", is_booked=False)
        self.seat_a2 = Seat.objects.create(theater=self.theater, screen=self.screen, row="A", seat_number="A2", is_booked=False)
        self.seat_b1 = Seat.objects.create(theater=self.theater, screen=self.screen, row="B", seat_number="B1", is_booked=True)

        # 4. Create sample Booking and Payment
        self.booking = Booking.objects.create(
            user=self.normal_user,
            seat=self.seat_b1,
            movie=self.movie,
            theater=self.theater
        )
        self.payment = Payment.objects.create(
            user=self.normal_user,
            amount=300.00,
            order_id="pi_test_admin_123",
            payment_id="pi_test_admin_123",
            provider="STRIPE",
            status="SUCCESS",
            booking=self.booking
        )

    def test_unauthorized_user_redirected_from_admin(self):
        """Normal users must not access admin views."""
        self.client.login(username='regular_customer', password='custpassword123')
        res = self.client.get('/admin/')
        # Redirects to login
        self.assertIn(res.status_code, [302, 403])

    def test_superuser_dashboard_loads_with_ticketmitra_operations(self):
        """Superuser accessing /admin/ receives TicketMitra Operations Dashboard."""
        self.client.login(username='admin_boss', password='adminpassword123')
        res = self.client.get('/admin/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "TicketMitra Operations")
        self.assertContains(res, "Total Movies")
        self.assertContains(res, "Live Seat Status")
        self.assertContains(res, "Theater Management Overview")

    def test_admin_movie_crud_changes_are_reflected_on_movie_page(self):
        self.client.login(username='admin_boss', password='adminpassword123')
        admin_movies_url = reverse('admin_movies')
        release_date = timezone.now().date().isoformat()

        add_response = self.client.post(admin_movies_url, {
            'action': 'add_movie',
            'title': 'Admin Managed Feature',
            'name': 'Admin Managed Feature',
            'release_date': release_date,
            'original_language': 'en',
            'runtime': '111',
            'age_certification': 'UA',
            'rating': '7.8',
            'trailer_url': 'https://youtu.be/YoHD9XEInc0',
            'description': 'Description saved by the movie administrator.',
            'is_showing': 'on',
        })
        self.assertEqual(add_response.status_code, 302)
        movie = Movie.objects.get(title='Admin Managed Feature')
        detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': movie.id}))
        self.assertContains(detail, 'Description saved by the movie administrator.')
        self.assertContains(detail, 'Admin Managed Feature')

        self.client.post(admin_movies_url, {
            'action': 'edit_movie',
            'movie_id': movie.id,
            'title': 'Admin Edited Feature',
            'release_date': release_date,
            'original_language': 'en',
            'runtime': '120',
            'age_certification': 'UA',
            'rating': '8.1',
            'trailer_url': 'https://youtu.be/YoHD9XEInc0',
            'description': 'Description updated by an administrator.',
            'is_showing': 'on',
        })
        movie.refresh_from_db()
        self.assertEqual(movie.title, 'Admin Edited Feature')
        edited_detail = self.client.get(reverse('movie_detail', kwargs={'movie_id': movie.id}))
        self.assertContains(edited_detail, 'Description updated by an administrator.')

        self.client.post(admin_movies_url, {'action': 'delete_movie', 'movie_id': movie.id})
        self.assertFalse(Movie.objects.filter(id=movie.id).exists())

    def test_admin_does_not_invent_missing_movie_metadata(self):
        self.client.login(username='admin_boss', password='adminpassword123')
        response = self.client.post(reverse('admin_movies'), {
            'action': 'add_movie',
            'title': 'Metadata Pending Film',
            'release_date': '',
            'original_language': '',
            'runtime': '',
            'age_certification': '',
            'rating': '',
            'trailer_url': '',
            'description': '',
        })
        self.assertEqual(response.status_code, 302)
        movie = Movie.objects.get(title='Metadata Pending Film')
        self.assertIsNone(movie.release_date)
        self.assertIsNone(movie.original_language)
        self.assertIsNone(movie.runtime)
        self.assertIsNone(movie.age_certification)
        self.assertEqual(movie.rating, 0)
        self.assertEqual(movie.status, 'DRAFT')

    def test_standard_admin_exposes_taxonomy_cast_posters_and_show_schedule_forms(self):
        self.client.login(username='admin_boss', password='adminpassword123')
        for route_name in ('admin:movies_genre_add', 'admin:movies_language_add', 'admin:movies_castmember_add'):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)

        movie_change = self.client.get(reverse('admin:movies_movie_change', args=[self.movie.id]))
        self.assertEqual(movie_change.status_code, 200)
        self.assertContains(movie_change, 'genres')
        self.assertContains(movie_change, 'languages')
        self.assertContains(movie_change, 'cast_members')
        self.assertContains(movie_change, 'posters')
        self.assertContains(movie_change, 'time')

    def test_standard_admin_can_create_taxonomy_and_cast_records(self):
        self.client.login(username='admin_boss', password='adminpassword123')
        self.client.post(reverse('admin:movies_genre_add'), {'name': 'Mystery', 'tmdb_id': '99991'})
        self.client.post(reverse('admin:movies_language_add'), {'name': 'Konkani', 'code': 'kok'})
        self.client.post(reverse('admin:movies_castmember_add'), {
            'name': 'Audit Actor', 'character': 'Lead', 'tmdb_id': '',
            'profile_path': '', 'profile_image_url': '',
        })
        from movies.models import CastMember, Genre, Language
        self.assertTrue(Genre.objects.filter(name='Mystery', tmdb_id=99991).exists())
        self.assertTrue(Language.objects.filter(name='Konkani', code='kok').exists())
        self.assertTrue(CastMember.objects.filter(name='Audit Actor', character='Lead').exists())

    def test_custom_admin_showtime_creation_updates_live_catalog_and_seats(self):
        self.client.login(username='admin_boss', password='adminpassword123')
        show_date = (timezone.now() + timedelta(days=2)).date().isoformat()
        response = self.client.post('/admin/showtimes/', {
            'action': 'add_showtime',
            'movie_id': self.movie.id,
            'theater_name': self.screen.theater_name,
            'screen_id': self.screen.id,
            'show_date': show_date,
            'show_time': '18:45',
            'price': '325.00',
        })
        self.assertEqual(response.status_code, 302)
        showtime = Theater.objects.get(movie=self.movie, screen=self.screen, price='325.00')
        self.assertEqual(showtime.time.date().isoformat(), show_date)
        self.assertEqual(Seat.objects.filter(theater=showtime).count(), self.screen.capacity)

    def test_theater_detail_admin_view(self):
        """Theater detail page displays venue stats and screen cards."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_theater_detail', kwargs={'theater_id': self.theater.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "INOX Galleria")
        self.assertContains(res, "Screen 1")
        self.assertContains(res, "Manage Visual Seats")

    def test_screen_detail_admin_view(self):
        """Screen detail page displays capacity, seat counts, and showtimes."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_screen_detail', kwargs={'screen_id': self.screen.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Screen 1")
        self.assertContains(res, "IMAX")

    def test_visual_seat_map_view(self):
        """Visual seat map renders actual database seats in grid rows."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_manage_seats_theater', kwargs={'theater_id': self.theater.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "A1")
        self.assertContains(res, "B1")
        self.assertContains(res, "available")
        self.assertContains(res, "booked")

    def test_seat_action_api_block_and_unblock(self):
        """Admin can block and unblock unbooked seats."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_seat_action')

        # Block A1
        res = self.client.post(url, data={'action': 'block', 'seat_id': self.seat_a1.id})
        self.assertEqual(res.status_code, 200)
        self.seat_a1.refresh_from_db()
        self.assertTrue(self.seat_a1.is_blocked)

        # Unblock A1
        res = self.client.post(url, data={'action': 'unblock', 'seat_id': self.seat_a1.id})
        self.assertEqual(res.status_code, 200)
        self.seat_a1.refresh_from_db()
        self.assertFalse(self.seat_a1.is_blocked)

    def test_seat_action_cannot_block_booked_seat(self):
        """Cannot block seat with existing booking."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_seat_action')
        res = self.client.post(url, data={'action': 'block', 'seat_id': self.seat_b1.id})
        self.assertEqual(res.status_code, 400)

    def test_seat_action_add_seat(self):
        """Admin can add a single seat dynamically."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_seat_action')
        res = self.client.post(url, data={
            'action': 'add_seat',
            'theater_id': self.theater.id,
            'row': 'A',
            'seat_number': 'A9',
            'seat_type': 'REGULAR'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Seat.objects.filter(theater=self.theater, seat_number='A9').exists())

    def test_seat_action_reset_test_seats_preserves_bookings(self):
        """Reset test seats must NEVER delete or corrupt confirmed booking records."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_seat_action')

        # Make A1 blocked
        self.seat_a1.is_blocked = True
        self.seat_a1.save()

        res = self.client.post(url, data={
            'action': 'reset_test_seats',
            'theater_id': self.theater.id
        })
        self.assertEqual(res.status_code, 200)

        # A1 is unblocked
        self.seat_a1.refresh_from_db()
        self.assertFalse(self.seat_a1.is_blocked)

        # B1 booking is 100% intact!
        self.seat_b1.refresh_from_db()
        self.assertTrue(self.seat_b1.is_booked)
        self.assertTrue(Booking.objects.filter(id=self.booking.id).exists())

    def test_bulk_add_seats_view(self):
        """Bulk add seats generates rows without duplicates."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_bulk_add_seats')
        res = self.client.post(url, data={
            'theater_id': self.theater.id,
            'start_row': 'C',
            'end_row': 'D',
            'seats_per_row': 5,
            'seat_type': 'REGULAR'
        })
        # Redirects to visual seat map
        self.assertEqual(res.status_code, 302)
        # Should have created C1..C5 and D1..D5 = 10 seats
        self.assertEqual(Seat.objects.filter(theater=self.theater, row__in=['C', 'D']).count(), 10)

    def test_analytics_admin_view(self):
        """Analytics view loads charts and revenue figures."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_analytics')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Business Intelligence & Analytics")
        self.assertContains(res, "Chart.js")

    def test_analytics_date_filtering(self):
        """Analytics view dynamically supports preset and custom date range filters."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_analytics')
        
        # Test presets
        for preset in ['today', 'last_7_days', 'last_30_days', 'this_month', 'this_year', 'all_time']:
            res = self.client.get(f"{url}?preset={preset}")
            self.assertEqual(res.status_code, 200)

        # Test custom date range
        res = self.client.get(f"{url}?start_date=2026-01-01&end_date=2026-12-31")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "2026-01-01 to 2026-12-31")

    def test_analytics_csv_exports(self):
        """Analytics export endpoint generates valid CSV for all report types."""
        self.client.login(username='admin_boss', password='adminpassword123')
        export_url = reverse('admin_analytics_export')

        for report in ['comprehensive', 'revenue_trend', 'movies', 'theaters', 'peak_hours', 'cancellations', 'users']:
            res = self.client.get(f"{export_url}?report={report}")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')
            self.assertIn('attachment; filename=', res['Content-Disposition'])
            self.assertTrue(len(res.content) > 0)

    def test_analytics_access_control(self):
        """Only staff/admin accounts can access dashboard and exports."""
        self.client.logout()
        url = reverse('admin_analytics')
        res = self.client.get(url)
        # Unauthenticated user redirected to admin login
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login/', res['Location'])

        export_url = reverse('admin_analytics_export')
        res_exp = self.client.get(export_url)
        self.assertEqual(res_exp.status_code, 302)

    def test_global_search_view(self):
        """Global search finds matching movies and bookings."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_global_search') + "?q=Inception"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Inception IMAX")

    def test_quick_booking_view(self):
        """Quick booking controlled admin test flow loads movie and theater picker."""
        self.client.login(username='admin_boss', password='adminpassword123')
        url = reverse('admin_quick_booking') + f"?movie_id={self.movie.id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Inception IMAX")
        self.assertContains(res, "Select Seats")
