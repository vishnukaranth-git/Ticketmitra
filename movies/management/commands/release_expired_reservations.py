from django.core.management.base import BaseCommand
from django.utils import timezone

from movies.models import SeatReservation


class Command(BaseCommand):
    help = "Release all temporary seat reservations that have exceeded their 2-minute expiration time."

    def handle(self, *args, **options):
        now = timezone.now()
        expired_reservations = SeatReservation.objects.filter(
            status='ACTIVE',
            expires_at__lte=now
        )
        count = expired_reservations.count()

        if count > 0:
            updated = expired_reservations.update(status='EXPIRED')
            self.stdout.write(self.style.SUCCESS(
                f"Successfully released {updated} expired seat reservation(s) at {now.strftime('%Y-%m-%d %H:%M:%S')}."
            ))
        else:
            self.stdout.write(self.style.NOTICE(
                f"No active expired seat reservations found to release at {now.strftime('%Y-%m-%d %H:%M:%S')}."
            ))
