from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from movies.models import Movie, Screen, Seat, Theater


class Command(BaseCommand):
    help = "Seeds 3 test theaters in Bengaluru with 5 screens each and 30 available seats per screen (450 total seats)."

    def handle(self, *args, **options):
        # UTF-8 stdout wrapper for safe cross-platform symbols
        def safe_print(text):
            try:
                self.stdout.write(text)
            except UnicodeEncodeError:
                ascii_text = text.replace('✓', '[OK]').replace('—', '-')
                self.stdout.write(ascii_text)

        safe_print("Creating test theaters...\n")

        theaters_data = [
            {
                "name": "INOX Galleria",
                "address": "Galleria Mall, Bellary Rd, Yelahanka",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": "560064",
                "latitude": 13.100700,
                "longitude": 77.596300,
            },
            {
                "name": "Bhartiya Mall",
                "address": "Bhartiya City, Thanisandra Main Rd",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": "560064",
                "latitude": 13.074700,
                "longitude": 77.636900,
            },
            {
                "name": "Mall of Asia",
                "address": "Bellary Rd, Byatarayanapura, Sahakar Nagar",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": "560092",
                "latitude": 13.063200,
                "longitude": 77.589800,
            }
        ]

        screens_data = [
            ("Screen 1", "IMAX"),
            ("Screen 2", "4DX"),
            ("Screen 3", "PXL"),
            ("Screen 4", "MX4D"),
            ("Screen 5", "GOLD")
        ]

        # Seat configuration: 5 rows (A-E), 6 columns (1-6) = 30 seats
        # Rows A-B: REGULAR, Rows C-D: PREMIUM, Row E: VIP
        rows_config = [
            ('A', 'REGULAR'),
            ('B', 'REGULAR'),
            ('C', 'PREMIUM'),
            ('D', 'PREMIUM'),
            ('E', 'VIP'),
        ]

        # Find or select a default movie to associate showtimes with
        movie = (
            Movie.objects.filter(status='CURRENT', release_date__lte=timezone.now().date()).first()
            or Movie.objects.filter(original_language__in=['kn', 'ta', 'te', 'ml']).first()
            or Movie.objects.first()
        )
        if not movie:
            movie = Movie.objects.create(
                name="TicketMitra Premiere",
                title="TicketMitra Premiere",
                tmdb_id=99901,
                rating=8.5,
                release_date=timezone.now().date(),
                runtime=150,
                status='CURRENT'
            )
        elif movie.status != 'CURRENT':
            movie.status = 'CURRENT'
            movie.save(update_fields=['status'])

        base_time = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
        showtime_offsets = [0, 3.5, 6.5, 9.5, 12]  # showtimes throughout the day

        total_theaters_count = len(theaters_data)
        total_screens_count = 0
        total_seats_count = 0

        for t_idx, t_info in enumerate(theaters_data):
            theater_name = t_info["name"]
            safe_print(f"✓ {theater_name} (Lat: {t_info['latitude']}, Lon: {t_info['longitude']})")

            # Update existing records for this theater name with coordinates
            Theater.objects.filter(name=theater_name).update(
                address=t_info["address"],
                city=t_info["city"],
                state=t_info["state"],
                pincode=t_info["pincode"],
                latitude=t_info["latitude"],
                longitude=t_info["longitude"],
            )

            for s_idx, (screen_name, screen_type) in enumerate(screens_data):
                # 1. Get or create Screen
                screen, _ = Screen.objects.get_or_create(
                    theater_name=theater_name,
                    name=screen_name,
                    defaults={
                        'screen_type': screen_type,
                        'capacity': 30,
                        'active': True
                    }
                )
                if screen.screen_type != screen_type or screen.capacity != 30 or not screen.active:
                    screen.screen_type = screen_type
                    screen.capacity = 30
                    screen.active = True
                    screen.save()
                total_screens_count += 1

                # 2. Get or create Theater Showtime record
                show_time = base_time + timedelta(hours=showtime_offsets[s_idx])
                theater_record, created = Theater.objects.get_or_create(
                    name=theater_name,
                    screen=screen,
                    movie=movie,
                    defaults={
                        'time': show_time,
                        'location': f"{t_info['city']}, {t_info['state']}",
                        'address': t_info['address'],
                        'city': t_info['city'],
                        'state': t_info['state'],
                        'pincode': t_info['pincode'],
                        'latitude': t_info['latitude'],
                        'longitude': t_info['longitude'],
                        'active': True
                    }
                )
                if not created:
                    theater_record.address = t_info['address']
                    theater_record.city = t_info['city']
                    theater_record.state = t_info['state']
                    theater_record.pincode = t_info['pincode']
                    theater_record.latitude = t_info['latitude']
                    theater_record.longitude = t_info['longitude']
                    theater_record.save(update_fields=['address', 'city', 'state', 'pincode', 'latitude', 'longitude'])

                # 3. Create/verify 30 Seats for this Screen & Theater (All start AVAILABLE)
                screen_seats_count = 0
                for row_letter, seat_category in rows_config:
                    for col in range(1, 7):
                        seat_no = f"{row_letter}{col}"
                        seat, _s_created = Seat.objects.get_or_create(
                            theater=theater_record,
                            seat_number=seat_no,
                            defaults={
                                'screen': screen,
                                'row': row_letter,
                                'seat_type': seat_category,
                                'is_booked': False,
                                'is_blocked': False,
                            }
                        )
                        # Ensure fields and unbooked status are always preserved
                        if seat.screen != screen or seat.row != row_letter or seat.seat_type != seat_category or seat.is_booked:
                            seat.screen = screen
                            seat.row = row_letter
                            seat.seat_type = seat_category
                            seat.is_booked = False
                            seat.is_blocked = False
                            seat.save(update_fields=['screen', 'row', 'seat_type', 'is_booked', 'is_blocked'])

                        screen_seats_count += 1
                        total_seats_count += 1

                safe_print(f"  ✓ {screen_name} — {screen_type} — {screen_seats_count} seats")

            safe_print("")

        safe_print("Total:")
        safe_print(f"{total_theaters_count} theaters")
        safe_print(f"{total_screens_count} screens")
        safe_print(f"{total_seats_count} seats\n")
        safe_print("All seats initialized as AVAILABLE.")
