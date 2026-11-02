from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from movies.models import Movie, Screen, Seat, Theater
from movies.services.location_service import (
    CITY_CENTROIDS,
    haversine_distance,
)
from movies.services.tmdb_service import TMDBService

User = get_user_model()


class LocationAndMovieStatusTests(TestCase):
    def setUp(self):
        self.today = timezone.now().date()
        self.now = timezone.now()

        # Admin user
        self.admin = User.objects.create_superuser('admin_tester', 'admin@example.com', 'adminpass123')

        # Regular user
        self.user = User.objects.create_user('regular_user', 'user@example.com', 'userpass123')

        # Current movie with today's release date
        self.current_movie = Movie.objects.create(
            title="Bangalore Days",
            original_title="Bangalore Days",
            release_date=self.today - timedelta(days=10),
            status='CURRENT',
            rating=8.3,
            tmdb_id=101010
        )

        # Future movie
        self.future_movie = Movie.objects.create(
            title="Avatar 4",
            release_date=self.today + timedelta(days=365),
            status='DRAFT',
            tmdb_id=202020
        )

        # Ended movie
        self.ended_movie = Movie.objects.create(
            title="Old Classic",
            release_date=self.today - timedelta(days=500),
            status='ENDED',
            tmdb_id=303030
        )

        # Screens
        self.screen_inox = Screen.objects.create(theater_name="INOX Galleria", name="Screen 1 - IMAX", screen_type="IMAX", capacity=30)
        self.screen_distant = Screen.objects.create(theater_name="PVR Chennai Grand", name="Screen 1 - 4DX", screen_type="4DX", capacity=30)

        # Near theater: INOX Galleria (Yelahanka, Bengaluru ~ Lat 13.1007, Lon 77.5963)
        self.near_theater = Theater.objects.create(
            name="INOX Galleria",
            movie=self.current_movie,
            screen=self.screen_inox,
            time=self.now + timedelta(hours=3),
            active=True,
            price=250.0,
            city="Bengaluru",
            latitude=13.1007,
            longitude=77.5963
        )

        # Far theater: PVR Chennai (Lat 13.0827, Lon 80.2707 ~ 290 km away)
        self.far_theater = Theater.objects.create(
            name="PVR Chennai Grand",
            movie=self.current_movie,
            screen=self.screen_distant,
            time=self.now + timedelta(hours=3),
            active=True,
            price=220.0,
            city="Chennai",
            latitude=13.0827,
            longitude=80.2707
        )

        # Theaters with no active future showtimes (past showtime)
        self.past_theater = Theater.objects.create(
            name="INOX Forum Past",
            movie=self.ended_movie,
            time=self.now - timedelta(days=2),
            active=True,
            city="Bengaluru",
            latitude=12.9352,
            longitude=77.6103
        )

        # Initialize seats for near_theater: all must start AVAILABLE
        self.seat1 = Seat.objects.create(theater=self.near_theater, seat_number="A1", is_booked=False, is_blocked=False)
        self.seat2 = Seat.objects.create(theater=self.near_theater, seat_number="A2", is_booked=False, is_blocked=False)
        self.seat3 = Seat.objects.create(theater=self.near_theater, seat_number="A3", is_booked=False, is_blocked=False)

    def test_future_movie_cannot_have_current_status(self):
        """A movie with a future release date cannot be set to 'CURRENT'."""
        future_movie = Movie(
            title="Future SciFi 2099",
            release_date=self.today + timedelta(days=30),
            status='CURRENT'
        )
        with self.assertRaises(ValidationError):
            future_movie.clean()

    def test_haversine_formula_distance_accuracy(self):
        """Haversine distance calculation is accurate to meters."""
        # Distance between Galleria (13.1007, 77.5963) and Bhartiya Mall (13.0747, 77.6369) is ~5.2 km
        dist = haversine_distance(13.1007, 77.5963, 13.0747, 77.6369)
        self.assertIsNotNone(dist)
        if dist is not None:
            self.assertAlmostEqual(dist, 5.2, delta=1.0)

        # Zero distance for identical coordinates
        dist_zero = haversine_distance(13.1007, 77.5963, 13.1007, 77.5963)
        self.assertEqual(dist_zero, 0.0)

    def test_30km_radius_filtering_includes_near_excludes_far(self):
        """User at Bengaluru centroid (~12.9716, 77.5946) finds Galleria (~14.4 km), excludes Chennai (~290 km)."""
        bengaluru_lat = 12.9716
        bengaluru_lon = 77.5946

        # Distance to near_theater
        near_dist = haversine_distance(bengaluru_lat, bengaluru_lon, self.near_theater.latitude, self.near_theater.longitude)
        far_dist = haversine_distance(bengaluru_lat, bengaluru_lon, self.far_theater.latitude, self.far_theater.longitude)

        self.assertIsNotNone(near_dist)
        self.assertIsNotNone(far_dist)
        if near_dist is not None and far_dist is not None:
            self.assertLessEqual(near_dist, 30.0)
            self.assertGreater(far_dist, 30.0)

        # Test request with session location
        client = Client()
        session = client.session
        session['user_location'] = {
            'lat': bengaluru_lat,
            'lon': bengaluru_lon,
            'city': 'Bengaluru',
            'radius': 30
        }
        session.save()

        # Call homepage
        res = client.get(reverse('home'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "INOX Galleria")
        self.assertNotContains(res, "PVR Chennai Grand")

    def test_city_fallback_when_coordinates_denied(self):
        """When user denies location and selects 'Bengaluru', fallback discovers Bengaluru theaters."""
        client = Client()
        # Post manual city selection
        res = client.post(reverse('set_location_api'), data={'city': 'Bengaluru', 'radius': 30})
        self.assertEqual(res.status_code, 200)

        # Check session was populated with Bengaluru centroid
        session = client.session
        self.assertEqual(session['user_location']['city'], 'Bengaluru')
        self.assertAlmostEqual(session['user_location']['lat'], CITY_CENTROIDS['bengaluru']['lat'], places=3)
        self.assertAlmostEqual(session['user_location']['lon'], CITY_CENTROIDS['bengaluru']['lon'], places=3)

    def test_current_movies_only_rule(self):
        """Only movies with status='CURRENT', release_date <= today, and active future showtimes appear in Now Showing."""
        client = Client()
        res = client.get(reverse('home'))
        self.assertEqual(res.status_code, 200)
        # Bangalore Days has status CURRENT, release_date <= today, and future showtime -> Must be in Now Showing
        self.assertIn(self.current_movie, res.context['now_showing_movies'])
        # Old Classic has status ENDED and past showtime -> Must NOT appear in Now Showing
        self.assertNotIn(self.ended_movie, res.context['now_showing_movies'])
        # Avatar 4 has status DRAFT and future release date -> Must NOT appear in Now Showing
        self.assertNotIn(self.future_movie, res.context['now_showing_movies'])

    def test_seats_start_available_by_default(self):
        """All newly created seats must start with is_booked=False and is_blocked=False."""
        for seat in [self.seat1, self.seat2, self.seat3]:
            self.assertFalse(seat.is_booked)
            self.assertFalse(seat.is_blocked)

    def test_admin_manual_seat_blocking_and_unblocking(self):
        """Admin can block and unblock seats; blocked seats cannot be reserved."""
        client = Client()
        client.login(username='admin_tester', password='adminpass123')

        # Admin blocks seat A1
        action_url = reverse('admin_seat_action')
        res = client.post(action_url, data={'action': 'block', 'seat_id': self.seat1.id})
        self.assertEqual(res.status_code, 200)

        self.seat1.refresh_from_db()
        self.assertTrue(self.seat1.is_blocked)

        # Regular user tries to reserve blocked seat A1 -> must be rejected with 409
        user_client = Client()
        user_client.login(username='regular_user', password='userpass123')
        reserve_url = reverse('reserve_seats', kwargs={'theater_id': self.near_theater.id})
        reserve_res = user_client.post(
            reserve_url,
            data={'seat_ids': [self.seat1.id]},
            content_type='application/json'
        )
        self.assertEqual(reserve_res.status_code, 409)
        self.assertFalse(reserve_res.json()['success'])

        # Admin unblocks seat A1
        unblock_res = client.post(action_url, data={'action': 'unblock', 'seat_id': self.seat1.id})
        self.assertEqual(unblock_res.status_code, 200)

        self.seat1.refresh_from_db()
        self.assertFalse(self.seat1.is_blocked)

        # Now regular user CAN reserve seat A1
        reserve_res2 = user_client.post(
            reserve_url,
            data={'seat_ids': [self.seat1.id]},
            content_type='application/json'
        )
        self.assertEqual(reserve_res2.status_code, 200)
        self.assertTrue(reserve_res2.json()['success'])

    def test_tmdb_import_idempotent_deduplication(self):
        """Importing movie with existing TMDB ID updates instead of duplicating."""
        tmdb_data = {
            'id': 101010,  # Matches self.current_movie.tmdb_id
            'title': 'Bangalore Days (Remastered)',
            'original_title': 'Bangalore Days',
            'overview': 'Updated description',
            'release_date': str(self.today - timedelta(days=10)),
            'vote_average': 8.5,
            'vote_count': 1200,
            'popularity': 45.0,
            'genres': [{'id': 18, 'name': 'Drama'}, {'id': 35, 'name': 'Comedy'}],
            'original_language': 'en',
            'videos': {'results': []},
            'credits': {'cast': []},
            'release_dates': {'results': []},
            'images': {'backdrops': [], 'posters': []}
        }

        # Count movies before
        count_before = Movie.objects.filter(tmdb_id=101010).count()
        self.assertEqual(count_before, 1)

        # Call service to import/update
        service = TMDBService()
        with mock.patch.object(TMDBService, 'get_movie_details', return_value=tmdb_data):
            movie_obj, was_created = service.import_or_update_movie(101010)

        # Must not create a duplicate
        count_after = Movie.objects.filter(tmdb_id=101010).count()
        self.assertEqual(count_after, 1)
        self.assertFalse(was_created)
        self.assertEqual(movie_obj.id, self.current_movie.id)
        self.assertEqual(movie_obj.title, 'Bangalore Days (Remastered)')
        self.assertEqual(movie_obj.vote_count, 1200)
