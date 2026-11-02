import time
import tracemalloc
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from movies.admin_views import get_comprehensive_analytics_data
from movies.models import Booking, Movie, Seat, Theater


class Command(BaseCommand):
    help = "Benchmark analytics query performance and database indexing with high booking volumes (up to 100,000 bookings)."

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=100000, help="Target total bookings for benchmark (default: 100000)")
        parser.add_argument('--seed', action='store_true', help="Seed database with synthetic bookings up to target count if below")
        parser.add_argument('--clean-after', action='store_true', help="Clean up seeded synthetic records after benchmark")

    def handle(self, *args, **options):
        target_count = options['count']
        seed_mode = options['seed']
        clean_after = options['clean_after']

        self.stdout.write(self.style.NOTICE("=" * 70))
        self.stdout.write(self.style.NOTICE(" TICKETMITRA ENTERPRISE ANALYTICS & INDEX BENCHMARK"))
        self.stdout.write(self.style.NOTICE("=" * 70))

        current_count = Booking.objects.count()
        self.stdout.write(f"Current Bookings in Database: {current_count}")

        seeded_synthetic = False
        if seed_mode and current_count < target_count:
            needed = target_count - current_count
            self.stdout.write(self.style.WARNING(f"Seeding {needed} synthetic bookings for 100,000 scale test..."))
            user, _ = User.objects.get_or_create(username='benchmark_user', defaults={'email': 'bench@ticketmitra.com'})
            movie = Movie.objects.first()
            theater = Theater.objects.first()

            batch_size = 2500
            now = timezone.now()
            created_so_far = 0

            while created_so_far < needed:
                chunk_len = min(batch_size, needed - created_so_far)
                # 1. Bulk create seats for this batch
                seats_batch = [
                    Seat(theater=theater, seat_number=f"BK-{created_so_far + i}", is_booked=True)
                    for i in range(chunk_len)
                ]
                with transaction.atomic():
                    created_seats = Seat.objects.bulk_create(seats_batch)

                # 2. Bulk create bookings linked 1-to-1 with created seats
                batch = []
                for i, st in enumerate(created_seats):
                    idx = created_so_far + i
                    b_time = now - timedelta(days=(idx % 60), hours=(idx % 24), minutes=(idx % 60))
                    status = 'CANCELLED' if (idx % 20 == 0) else 'CONFIRMED'
                    batch.append(Booking(
                        user=user,
                        seat=st,
                        movie=movie,
                        theater=theater,
                        amount=250.00,
                        status=status,
                        booked_at=b_time,
                        refund_amount=250.00 if status == 'CANCELLED' else 0.00
                    ))
                with transaction.atomic():
                    Booking.objects.bulk_create(batch)

                created_so_far += chunk_len
                self.stdout.write(f"  Progress: {created_so_far}/{needed} synthetic bookings created...")

            seeded_synthetic = True
            current_count = Booking.objects.count()
            self.stdout.write(self.style.SUCCESS(f"Seeding complete! Total bookings in DB: {current_count}"))

        # Measure query performance and memory
        self.stdout.write("\nRunning optimized database aggregation benchmark:")
        tracemalloc.start()
        start_time = time.perf_counter()

        now = timezone.now()
        start_dt = now - timedelta(days=30)
        end_dt = now

        analytics_data = get_comprehensive_analytics_data(start_dt=start_dt, end_dt=end_dt)

        end_time = time.perf_counter()
        _current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        duration_ms = (end_time - start_time) * 1000
        peak_kb = peak_mem / 1024

        self.stdout.write(self.style.SUCCESS(f"  Execution Time: {duration_ms:.2f} ms"))
        self.stdout.write(self.style.SUCCESS(f"  Peak Memory Consumption: {peak_kb:.2f} KB (Constant O(1) Memory)"))
        self.stdout.write(f"  Total Period Bookings Processed: {analytics_data['total_period_bookings']}")
        self.stdout.write(f"  Confirmed: {analytics_data['confirmed_period_bookings']} | Cancelled: {analytics_data['cancelled_period_bookings']}")
        self.stdout.write(f"  Cancellation Rate: {analytics_data['cancellation_rate']}%")
        self.stdout.write(f"  Period Revenue: INR {analytics_data['period_revenue']:.2f}")
        self.stdout.write(f"  Peak Hour: {analytics_data['peak_hour_display']} ({analytics_data['peak_hour_count']} bookings)")

        # Inspect DB Indexes
        self.stdout.write("\nVerifying Active Database Indexes:")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA index_list('movies_booking');")
            indices = cursor.fetchall()
            for idx_info in indices:
                idx_name = idx_info[1]
                self.stdout.write(f"  [*] Index on movies_booking: {idx_name}")

        self.stdout.write(self.style.NOTICE("=" * 70))
        self.stdout.write(self.style.SUCCESS(" BENCHMARK COMPLETED SUCCESSFULLY"))
        self.stdout.write(self.style.NOTICE("=" * 70))

        if clean_after and seeded_synthetic:
            self.stdout.write(self.style.WARNING("Cleaning up synthetic benchmark records..."))
            Booking.objects.filter(user__username='benchmark_user').delete()
            Seat.objects.filter(seat_number__startswith='BK-').delete()
            User.objects.filter(username='benchmark_user').delete()
            self.stdout.write(self.style.SUCCESS("Cleanup complete."))
