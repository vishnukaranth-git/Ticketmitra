from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from movies.models import CinemaVenue, Movie, Screen, Seat, Theater


class Command(BaseCommand):
    help = "Seeds cinema venues, 5 screens each, and 100% available seats for test theatres without fake bookings."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting TicketMitra Cinema Data Seeding..."))

        now = timezone.now()

        # 1. TEST THEATRES SPECIFICATION
        test_theatres_data = [
            {
                'name': 'INOX Galleria',
                'address': 'Galleria Mall, Yelahanka',
                'city': 'Bengaluru',
                'state': 'Karnataka',
                'pincode': '560064',
                'latitude': Decimal('13.100700'),
                'longitude': Decimal('77.596300'),
                'contact_number': '+91 80 4567 8901',
                'description': 'Premier multiplex in North Bengaluru featuring IMAX & 4DX immersive auditoriums.',
            },
            {
                'name': 'Bhartiya Mall',
                'address': 'Bhartiya City, Thanisandra Main Road',
                'city': 'Bengaluru',
                'state': 'Karnataka',
                'pincode': '560064',
                'latitude': Decimal('13.074500'),
                'longitude': Decimal('77.636600'),
                'contact_number': '+91 80 4567 8902',
                'description': 'State-of-the-art cinema complex with PXL giant screens and luxury Gold dining lounges.',
            },
            {
                'name': 'Mall of Asia',
                'address': 'Phoenix Mall of Asia, Bellary Road, Byatarayanapura',
                'city': 'Bengaluru',
                'state': 'Karnataka',
                'pincode': '560092',
                'latitude': Decimal('13.064200'),
                'longitude': Decimal('77.589800'),
                'contact_number': '+91 80 4567 8903',
                'description': 'Flagship luxury cinema destination in Bengaluru featuring IMAX and Dolby Atmos technology.',
            },
        ]

        # 2. 5 SCREENS PER THEATRE
        screens_spec = [
            {'name': 'Screen 1 – IMAX', 'screen_type': 'IMAX', 'capacity': 32},
            {'name': 'Screen 2 – 4DX', 'screen_type': '4DX', 'capacity': 32},
            {'name': 'Screen 3 – PXL', 'screen_type': 'PXL', 'capacity': 32},
            {'name': 'Screen 4 – Gold', 'screen_type': 'GOLD', 'capacity': 24},
            {'name': 'Screen 5 – Standard', 'screen_type': 'STANDARD', 'capacity': 32},
        ]

        # Fetch current movies for creating active showtimes
        current_movies = list(Movie.objects.filter(status='CURRENT').order_by('-popularity'))
        if not current_movies:
            current_movies = list(Movie.objects.all()[:5])

        created_venues_count = 0
        created_screens_count = 0
        created_showtimes_count = 0
        created_seats_count = 0

        # Sync existing distinct Theater venues into CinemaVenue first
        existing_venue_names = Theater.objects.values_list('name', flat=True).distinct()
        for v_name in existing_venue_names:
            sample_t = Theater.objects.filter(name=v_name).first()
            if sample_t and not CinemaVenue.objects.filter(name=v_name).exists():
                CinemaVenue.objects.create(
                    name=v_name,
                    address=sample_t.address or sample_t.location,
                    city=sample_t.city,
                    state=sample_t.state,
                    pincode=sample_t.pincode,
                    latitude=sample_t.latitude,
                    longitude=sample_t.longitude,
                    active=True
                )

        for t_info in test_theatres_data:
            venue_name = t_info['name']
            venue, v_created = CinemaVenue.objects.get_or_create(
                name=venue_name,
                defaults=t_info
            )
            if v_created:
                created_venues_count += 1
            self.stdout.write(f"  Venue: {venue.name} ({'Created' if v_created else 'Existing'})")

            # Create 5 Screens
            for idx, scr_spec in enumerate(screens_spec):
                screen, s_created = Screen.objects.get_or_create(
                    theater_name=venue_name,
                    name=scr_spec['name'],
                    defaults={
                        'screen_type': scr_spec['screen_type'],
                        'capacity': scr_spec['capacity'],
                        'active': True
                    }
                )
                if s_created:
                    created_screens_count += 1

                # Schedule showtimes for today and tomorrow with available current movies
                assigned_movie = current_movies[idx % len(current_movies)] if current_movies else None
                if assigned_movie:
                    # Showtime 1: Today Evening 19:30
                    show_time_1 = now.replace(hour=19, minute=30, second=0, microsecond=0)
                    if show_time_1 < now:
                        show_time_1 = now + timedelta(hours=2)

                    price_map = {'IMAX': 350.00, '4DX': 400.00, 'PXL': 300.00, 'GOLD': 450.00, 'STANDARD': 220.00}
                    t_price = price_map.get(str(scr_spec['screen_type']), 250.00)

                    theater_show, th_created = Theater.objects.get_or_create(
                        name=venue_name,
                        movie=assigned_movie,
                        screen=screen,
                        time=show_time_1,
                        defaults={
                            'location': t_info['address'],
                            'address': t_info['address'],
                            'city': t_info['city'],
                            'state': t_info['state'],
                            'pincode': t_info['pincode'],
                            'latitude': t_info['latitude'],
                            'longitude': t_info['longitude'],
                            'price': Decimal(str(t_price)),
                            'active': True
                        }
                    )
                    if th_created:
                        created_showtimes_count += 1

                    # Generate 32 Available Seats per Showtime
                    # Rows A, B (Regular), C (Premium), D (VIP)
                    rows_config = [
                        ('A', 'REGULAR'),
                        ('B', 'REGULAR'),
                        ('C', 'PREMIUM'),
                        ('D', 'VIP'),
                    ]
                    for row_ltr, cat in rows_config:
                        for col in range(1, 9):
                            seat_no = f"{row_ltr}{col}"
                            seat, seat_created = Seat.objects.get_or_create(
                                theater=theater_show,
                                seat_number=seat_no,
                                defaults={
                                    'screen': screen,
                                    'row': row_ltr,
                                    'seat_type': cat,
                                    'is_booked': False,
                                    'is_blocked': False,
                                }
                            )
                            if seat_created:
                                created_seats_count += 1
                            else:
                                # Ensure test seats are available if they were not already booked by real users
                                if not seat.is_booked and getattr(seat, 'is_blocked', False):
                                    seat.is_blocked = False
                                    seat.save(update_fields=['is_blocked'])

        self.stdout.write(self.style.SUCCESS(
            f"\nSeeding Complete!\n"
            f"  Theatres: {len(test_theatres_data)} checked ({created_venues_count} new)\n"
            f"  Screens: {created_screens_count} new screens created\n"
            f"  Showtimes: {created_showtimes_count} new showtimes scheduled\n"
            f"  Seats: {created_seats_count} AVAILABLE seats generated\n"
            f"  ALL newly created seats are 100% AVAILABLE (NO fake bookings, NO fake reservations).\n"
        ))
