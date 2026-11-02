import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Genre(models.Model):
    tmdb_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Language(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class CastMember(models.Model):
    tmdb_id = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=255)
    character = models.CharField(max_length=255, blank=True, null=True)
    profile_path = models.CharField(max_length=255, blank=True, null=True)
    profile_image_url = models.URLField(max_length=500, blank=True, null=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        if self.character:
            return f"{self.name} as {self.character}"
        return self.name

    def get_profile_url(self):
        if self.profile_image_url:
            return self.profile_image_url
        if self.profile_path:
            return f"https://image.tmdb.org/t/p/w185{self.profile_path}"
        return "https://via.placeholder.com/185x278?text=No+Photo"


class Movie(models.Model):
    # Preserved existing fields for full backward compatibility
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="movies/", blank=True, null=True)
    rating = models.DecimalField(max_digits=4, decimal_places=1, default=0.0)
    cast = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    # Extended TMDB and metadata fields
    title = models.CharField(max_length=255, blank=True, null=True)
    tmdb_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    original_title = models.CharField(max_length=255, blank=True, null=True)
    original_language = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    poster_url = models.URLField(max_length=500, blank=True, null=True)
    backdrop = models.ImageField(upload_to="movies/backdrops/", blank=True, null=True)
    backdrop_url = models.URLField(max_length=500, blank=True, null=True)
    release_date = models.DateField(blank=True, null=True, db_index=True)
    runtime = models.PositiveIntegerField(blank=True, null=True, help_text="Duration in minutes")
    age_certification = models.CharField(max_length=20, blank=True, null=True)
    trailer_url = models.URLField(max_length=500, blank=True, null=True)
    tmdb_rating = models.DecimalField(max_digits=4, decimal_places=1, default=0.0)
    vote_count = models.PositiveIntegerField(default=0)
    popularity = models.FloatField(default=0.0, db_index=True)

    imdb_id = models.CharField(max_length=30, blank=True, null=True)
    director = models.CharField(max_length=255, blank=True, null=True)
    is_in_active_catalog = models.BooleanField(default=True, db_index=True)

    # OTT and Advance Booking tracking
    ott_release_date = models.DateField(blank=True, null=True, help_text="Digital/OTT streaming release date")
    is_ott_only = models.BooleanField(default=False, db_index=True, help_text="True if movie is exclusively on streaming/OTT with no qualifying theatrical run")
    is_advance_booking_open = models.BooleanField(default=False, db_index=True, help_text="True when advance booking is officially open before theatrical release date")
    has_ott_release = models.BooleanField(default=False, db_index=True, help_text="True if available on streaming/OTT in India")
    ott_streaming_url = models.URLField(max_length=500, blank=True, null=True, help_text="Official watch/provider link in India")
    ott_providers = models.JSONField(blank=True, null=True, default=list, help_text="List of OTT streaming providers in India with name, logo_url, and link")

    # AI Movie Intelligence (Groq powered)
    ai_verdict = models.TextField(blank=True, null=True, help_text="AI critical verdict and curatorial highlight")
    ai_analysis = models.JSONField(blank=True, null=True, default=dict, help_text="AI movie analysis payload")

    STATUS_CHOICES = [
        ('CURRENT', 'Now Showing'),
        ('ADVANCE_BOOKING', 'Advance Booking'),
        ('UPCOMING', 'Coming Soon'),
        ('ENDED', 'Theatrical Run Ended'),
        ('OTT_ONLY', 'OTT / Streaming Only'),
        ('DRAFT', 'Draft'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CURRENT', db_index=True)

    # Relationships
    genres = models.ManyToManyField(Genre, blank=True, related_name='movies')
    languages = models.ManyToManyField(Language, blank=True, related_name='movies')
    cast_members = models.ManyToManyField(CastMember, blank=True, related_name='movies')

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['-popularity', '-release_date', 'name']
        indexes = [
            models.Index(fields=['release_date']),
            models.Index(fields=['popularity']),
            models.Index(fields=['rating']),
            models.Index(fields=['tmdb_rating']),
            models.Index(fields=['status']),
            models.Index(fields=['status', 'release_date']),
            models.Index(fields=['is_in_active_catalog', 'status']),
        ]

    def __str__(self):
        return self.title or self.name

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.status == 'CURRENT' and self.release_date and self.release_date > timezone.now().date():
            raise ValidationError({'status': "A movie with a future release date cannot be marked as 'Currently Showing'."})

    def save(self, *args, **kwargs):
        # Keep name and title in sync
        if not self.title and self.name:
            self.title = self.name
        elif not self.name and self.title:
            self.name = self.title

        # Keep legacy rating and tmdb_rating in sync if needed
        if self.tmdb_rating and (not self.rating or self.rating == 0.0):
            self.rating = self.tmdb_rating
        elif self.rating and (not self.tmdb_rating or self.tmdb_rating == 0.0):
            self.tmdb_rating = self.rating

        super().save(*args, **kwargs)

    def get_display_title(self):
        return self.title or self.name

    def get_poster_url(self):
        if self.image and hasattr(self.image, 'url') and self.image.name:
            try:
                return self.image.url
            except Exception:
                pass
        if self.poster_url:
            return self.poster_url
        # Fallback to primary poster if available
        primary_poster = self.posters.filter(is_primary=True).first()
        if primary_poster:
            return primary_poster.get_url()
        first_poster = self.posters.first()
        if first_poster:
            return first_poster.get_url()
        return "https://image.tmdb.org/t/p/w500/t6HIqrRAclMCA60NsSmeqe9RmNV.jpg"

    def get_backdrop_url(self):
        if self.backdrop and hasattr(self.backdrop, 'url') and self.backdrop.name:
            try:
                return self.backdrop.url
            except Exception:
                pass
        if self.backdrop_url:
            return self.backdrop_url
        return ""

    def has_active_showtimes(self, city=None, now_dt=None):
        if now_dt is None:
            now_dt = timezone.now()
        # Fast path if annotated and no city filter
        annotated_count = getattr(self, 'active_future_showtimes_count', None)
        if annotated_count is not None and not city:
            return annotated_count > 0
        qs = self.theaters.filter(active=True, time__gte=now_dt)
        if city:
            qs = qs.filter(city__iexact=city)
        return qs.exists()

    def get_release_status(self, city=None, now_dt=None, future_showtimes_exist=None):
        """
        Computes verified, date-aware and city-aware theatrical release status:
        - NOW_SHOWING: release_date <= today and has active future showtime in selected city/theaters
        - ADVANCE_BOOKING: release_date > today and has active future showtimes (or is_advance_booking_open)
        - COMING_SOON: release_date > today and no bookable showtime
        - OTT_ONLY: marked is_ott_only=True and has no qualifying theatrical run
        - RELEASE_ENDED: release_date <= today but has no active local showtimes (past run)
        - UNKNOWN: release_date is None and no active showtimes
        """
        if now_dt is None:
            now_dt = timezone.now()
        today = now_dt.date()

        if self.is_ott_only:
            return 'OTT_ONLY'

        if self.release_date is None:
            has_shows = future_showtimes_exist
            if has_shows is None:
                has_shows = self.has_active_showtimes(city=city, now_dt=now_dt)
            return 'NOW_SHOWING' if has_shows else 'UNKNOWN'

        has_shows = future_showtimes_exist
        if has_shows is None:
            has_shows = self.has_active_showtimes(city=city, now_dt=now_dt)

        if self.release_date > today:
            if has_shows or self.is_advance_booking_open or self.status == 'ADVANCE_BOOKING':
                return 'ADVANCE_BOOKING'
            return 'COMING_SOON'
        else:
            # release_date <= today
            if has_shows:
                return 'NOW_SHOWING'
            else:
                return 'RELEASE_ENDED'

    @property
    def dynamic_release_status(self):
        return self.get_release_status()

    @property
    def release_status_label(self):
        st = self.get_release_status()
        labels = {
            'NOW_SHOWING': 'Now Showing',
            'ADVANCE_BOOKING': 'Advance Booking',
            'COMING_SOON': 'Coming Soon',
            'OTT_ONLY': 'OTT / Streaming',
            'RELEASE_ENDED': 'Run Ended',
            'UNKNOWN': 'Release Date TBA',
        }
        return labels.get(st, 'Coming Soon')

    @property
    def release_status_badge_class(self):
        st = self.get_release_status()
        classes = {
            'NOW_SHOWING': 'badge-now-showing',
            'ADVANCE_BOOKING': 'badge-advance-booking',
            'COMING_SOON': 'badge-coming-soon',
            'OTT_ONLY': 'badge-ott-only',
            'RELEASE_ENDED': 'badge-run-ended',
            'UNKNOWN': 'badge-unknown',
        }
        return classes.get(st, 'badge-coming-soon')

    @property
    def is_recent_theatrical_release(self):
        if not self.release_date or self.is_ott_only:
            return False
        today = timezone.now().date()
        return (today - timezone.timedelta(days=14)) <= self.release_date <= today

    def is_released_this_week(self, ref_date=None):
        """Checks if Indian theatrical release occurred during current calendar week (Mon-Sun)."""
        if not self.release_date or self.is_ott_only:
            return False
        today = ref_date or timezone.now().date()
        start_of_week = today - timezone.timedelta(days=today.weekday())  # Monday
        end_of_week = start_of_week + timezone.timedelta(days=6)          # Sunday
        return start_of_week <= self.release_date <= end_of_week

    def get_countdown_display(self):
        """Returns dynamic countdown display string for upcoming movies."""
        if not self.release_date:
            return "Coming Soon"
        today = timezone.now().date()
        diff = (self.release_date - today).days
        if diff < 0:
            return "In Theatres"
        elif diff == 0:
            return "Releasing Today"
        elif diff == 1:
            return "Releasing Tomorrow"
        elif diff <= 7:
            return f"Releasing in {diff} Days"
        elif diff <= 30:
            weeks = max(1, diff // 7)
            return f"In {weeks} Week{'s' if weeks > 1 else ''}"
        else:
            return f"Releasing {self.release_date.strftime('%b %d')}"

    def get_primary_ott_provider(self):
        """Returns primary streaming watch provider info in India."""
        if self.ott_providers and isinstance(self.ott_providers, list) and len(self.ott_providers) > 0:
            # First look for subscription flatrate
            for prov in self.ott_providers:
                if prov.get('type') == 'flatrate':
                    return prov
            return self.ott_providers[0]
        if self.is_ott_only:
            return {
                'provider_name': 'OTT Streaming',
                'logo_url': '',
                'streaming_url': self.ott_streaming_url or 'https://www.themoviedb.org/',
                'type': 'flatrate'
            }
        return None

    @property
    def is_bookable(self):
        st = self.get_release_status()
        return st in ['NOW_SHOWING', 'ADVANCE_BOOKING'] and self.has_active_showtimes()

    def get_runtime_display(self):
        if not self.runtime or self.runtime <= 0:
            return None
        hours = self.runtime // 60
        mins = self.runtime % 60
        if hours > 0 and mins > 0:
            return f"{hours}h {mins}m"
        elif hours > 0:
            return f"{hours}h"
        return f"{mins}m"

    def get_show_end_cutoff(self, now=None):
        """Return the latest start time of a show that has finished, if runtime is known."""
        if not self.runtime or self.runtime <= 0:
            return None
        return (now or timezone.now()) - timedelta(minutes=self.runtime)

    def get_average_user_rating(self):
        avg = self.get_valid_reviews().aggregate(models.Avg('rating'))['rating__avg']
        if avg is not None:
            return round(avg, 1)
        return None

    def get_user_rating_display(self):
        avg = self.get_average_user_rating()
        if avg is not None:
            return f"★ {avg} / 5"
        return "No reviews yet"

    def get_review_count(self):
        return self.get_valid_reviews().count()

    def get_valid_reviews(self):
        """Only reviewed screenings with a staff check-in and elapsed runtime qualify."""
        show_end_cutoff = self.get_show_end_cutoff()
        if show_end_cutoff is None:
            return self.reviews.none()
        completed_booking = Booking.objects.filter(
            user_id=models.OuterRef('user_id'),
            movie_id=models.OuterRef('movie_id'),
            status='CONFIRMED',
            theater__time__lte=show_end_cutoff,
            attended_at__isnull=False,
        )
        return self.reviews.filter(
            is_reported=False,
            rating__gte=1,
            rating__lte=5,
        ).annotate(
            has_completed_booking=models.Exists(completed_booking),
        ).filter(has_completed_booking=True)

    def get_similar_movies(self, limit=6):
        genre_ids = list(self.genres.values_list('id', flat=True))
        language_ids = list(self.languages.values_list('id', flat=True))
        qs = Movie.objects.filter(is_in_active_catalog=True).exclude(id=self.id).exclude(status='DRAFT')

        # Prioritize matching BOTH language and genre
        lang_filter = models.Q()
        if self.original_language:
            lang_filter = models.Q(original_language=self.original_language)
        elif language_ids:
            lang_filter = models.Q(languages__id__in=language_ids)

        if genre_ids and (self.original_language or language_ids):
            # First look for same language + same genre
            exact_matches = list(qs.filter(lang_filter, genres__id__in=genre_ids).distinct().order_by('-popularity', '-release_date')[:limit])
            if len(exact_matches) >= limit:
                return exact_matches
            # Fill remaining with same language or same genre
            existing_ids = [m.id for m in exact_matches] + [self.id]
            more_matches = list(qs.exclude(id__in=existing_ids).filter(lang_filter | models.Q(genres__id__in=genre_ids)).distinct().order_by('-popularity', '-release_date')[:limit - len(exact_matches)])
            return exact_matches + more_matches

        if genre_ids:
            return list(qs.filter(genres__id__in=genre_ids).distinct().order_by('-popularity', '-release_date')[:limit])
        if self.original_language:
            return list(qs.filter(original_language=self.original_language).distinct().order_by('-popularity', '-release_date')[:limit])
        return []


    def get_trailer_embed_url(self):
        """Return an embeddable URL only for a valid YouTube video on an official host."""
        if not self.trailer_url:
            return None
        import re
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.trailer_url.strip())
        host = (parsed.hostname or '').lower()
        allowed_hosts = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com', 'youtu.be', 'www.youtu.be'}
        if parsed.scheme != 'https' or host not in allowed_hosts:
            return None

        video_id = None
        if host.endswith('youtu.be'):
            video_id = parsed.path.strip('/').split('/')[0]
        elif parsed.path.rstrip('/').split('/')[-1] in {'embed', 'v', 'shorts', 'live'}:
            return None
        elif any(part in {'embed', 'v', 'shorts', 'live'} for part in parsed.path.strip('/').split('/')[:-1]):
            video_id = parsed.path.strip('/').split('/')[-1]
        else:
            video_id = parse_qs(parsed.query).get('v', [None])[0]

        if video_id and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            return f"https://www.youtube.com/embed/{video_id}?enablejsapi=1&rel=0"
        return None

    def get_youtube_watch_url(self):
        """Returns standard youtube.com watch URL for fallback external viewing."""
        embed_url = self.get_trailer_embed_url()
        if not embed_url:
            return None
        import re
        match = re.search(r'/embed/([a-zA-Z0-9_-]{11})', embed_url)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}"
        return None


class MoviePoster(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='posters')
    image = models.ImageField(upload_to="movies/posters/", blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Poster for {self.movie.get_display_title()}"

    def get_url(self):
        if self.image and hasattr(self.image, 'url') and self.image.name:
            try:
                return self.image.url
            except Exception:
                pass
        return self.image_url or ""


class CinemaVenue(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)
    theatre_code = models.CharField(max_length=32, unique=True, null=True, blank=True)
    address = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, default='Bengaluru', db_index=True)
    state = models.CharField(max_length=100, default='Karnataka')
    pincode = models.CharField(max_length=10, blank=True, default='')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, db_index=True)
    contact_number = models.CharField(max_length=30, blank=True, default='')
    description = models.TextField(blank=True, default='')
    active = models.BooleanField(default=True, db_index=True)
    status = models.CharField(max_length=20, choices=[('ACTIVE', 'Active'), ('INACTIVE', 'Inactive'), ('CLOSED', 'Temporarily Closed')], default='ACTIVE', db_index=True)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    closed_weekdays = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.city})"


class Screen(models.Model):
    SCREEN_TYPES = [
        ('IMAX', 'IMAX'),
        ('4DX', '4DX'),
        ('PXL', 'PXL'),
        ('MX4D', 'MX4D'),
        ('GOLD', 'GOLD'),
        ('STANDARD', 'Standard'),
    ]

    theater_name = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=100)
    screen_type = models.CharField(max_length=50, choices=SCREEN_TYPES, default='IMAX')
    capacity = models.PositiveIntegerField(default=30)
    active = models.BooleanField(default=True)
    screen_number = models.PositiveSmallIntegerField(null=True, blank=True)
    operational_status = models.CharField(max_length=20, choices=[('ACTIVE', 'Active'), ('INACTIVE', 'Inactive'), ('MAINTENANCE', 'Under Maintenance')], default='ACTIVE', db_index=True)
    turnaround_minutes = models.PositiveSmallIntegerField(default=30)
    seating_layout = models.JSONField(default=dict, blank=True, help_text="Configured 2D/3D seat layout matrix and metadata")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('theater_name', 'name')
        ordering = ['theater_name', 'name']

    def __str__(self):
        return f"{self.theater_name} — {self.name} ({self.screen_type})"


class Theater(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='theaters')
    time = models.DateTimeField(db_index=True)
    screen = models.ForeignKey(Screen, on_delete=models.SET_NULL, null=True, blank=True, related_name='showtimes')
    location = models.CharField(max_length=255, default='Bengaluru, Karnataka')
    address = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, default='Bengaluru', db_index=True)
    state = models.CharField(max_length=100, default='Karnataka')
    pincode = models.CharField(max_length=10, blank=True, default='')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, db_index=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, default=180.00, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    ticket_prices = models.JSONField(default=dict, blank=True, help_text='Per-showtime ticket prices by seat category, stored as price snapshots for this show.')
    language = models.CharField(max_length=40, blank=True, default='')
    subtitles_available = models.BooleanField(default=False)
    operational_status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('SCHEDULED', 'Scheduled'),
            ('BOOKING_OPEN', 'Published / Open'),
            ('CANCELLED', 'Cancelled'),
            ('COMPLETED', 'Completed'),
        ],
        default='BOOKING_OPEN',
        db_index=True,
    )

    @property
    def end_time(self):
        duration = self.movie.runtime or 120
        return self.time + timedelta(minutes=duration)

    @property
    def cleaning_end_time(self):
        duration = self.movie.runtime or 120
        turnaround = self.screen.turnaround_minutes if self.screen else 30
        return self.time + timedelta(minutes=duration + turnaround)

    class Meta:
        ordering = ['name', 'time']
        indexes = [
            models.Index(fields=['name', 'time']),
            models.Index(fields=['city', 'time']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        screen_info = f" [{self.screen.name} - {self.screen.screen_type}]" if self.screen else ""
        return f'{self.name}{screen_info} - {self.movie.name} at {self.time}'

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.screen and self.name and self.screen.theater_name != self.name:
            raise ValidationError({'screen': f"Screen '{self.screen.name}' belongs to '{self.screen.theater_name}', not '{self.name}'."})
        if self.movie:
            if self.movie.status not in ['CURRENT', 'ADVANCE_BOOKING', 'UPCOMING']:
                raise ValidationError({'movie': "Only movies in active theatrical run or upcoming with advance booking can have showtimes."})
        if self.screen and self.time and self.movie_id:
            from datetime import timedelta
            runtime = self.movie.runtime or 120
            start = self.time
            end = start + timedelta(minutes=runtime)
            buffer_minutes = self.screen.turnaround_minutes or 0
            conflicts = Theater.objects.filter(screen=self.screen, active=True).exclude(pk=self.pk)
            for other in conflicts.select_related('movie'):
                other_end = other.time + timedelta(minutes=(other.movie.runtime or 120) + (other.screen.turnaround_minutes if other.screen_id else 30))
                if start < other_end and end + timedelta(minutes=buffer_minutes) > other.time:
                    raise ValidationError({'time': f"This show overlaps another screening in {self.screen.name}, including turnaround time."})
        if self.screen and self.screen.operational_status != 'ACTIVE':
            raise ValidationError({'screen': 'This screen is inactive or under maintenance.'})

    def distance_to(self, lat, lon):
        """Calculates distance in km from given coordinates using Haversine formula."""
        if self.latitude is None or self.longitude is None or lat is None or lon is None:
            return None
        import math
        try:
            lat1, lon1 = float(lat), float(lon)
            lat2, lon2 = float(self.latitude), float(self.longitude)
        except (ValueError, TypeError):
            return None
        R = 6371.0  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2.0) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(R * c, 2)

    def get_seat_price(self, seat_type='REGULAR'):
        normalized = (seat_type or 'REGULAR').upper()
        if self.ticket_prices and isinstance(self.ticket_prices, dict) and normalized in self.ticket_prices:
            try:
                return float(self.ticket_prices[normalized])
            except (ValueError, TypeError):
                pass
        plan_price = PricingPlan.resolve_price_for_showtime(self, normalized)
        if plan_price is not None:
            return plan_price
        return float(self.price or 180.00)

    def get_effective_pricing_snapshot(self):
        """Returns complete dict of category prices for this showtime."""
        categories = ['REGULAR', 'PREMIUM', 'VIP', 'RECLINER', 'ACCESSIBLE']
        return {cat: self.get_seat_price(cat) for cat in categories}


class Seat(models.Model):
    SEAT_TYPE_CHOICES = [
        ('REGULAR', 'Regular'),
        ('PREMIUM', 'Premium'),
        ('VIP', 'VIP'),
        ('RECLINER', 'Recliner'),
        ('ACCESSIBLE', 'Accessible'),
    ]

    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, null=True, blank=True, related_name='seats')
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, null=True, blank=True, related_name='seats')
    row = models.CharField(max_length=5, blank=True, default='')
    seat_number = models.CharField(max_length=10)
    seat_type = models.CharField(max_length=20, choices=SEAT_TYPE_CHOICES, default='REGULAR')
    is_booked = models.BooleanField(default=False, db_index=True)
    is_blocked = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['seat_number']
        indexes = [
            models.Index(fields=['theater', 'is_booked']),
            models.Index(fields=['screen', 'is_booked']),
        ]

    def __str__(self):
        th_name = self.theater.name if self.theater else (self.screen.name if self.screen else 'Unassigned')
        return f'{self.seat_number} in {th_name}'


class Booking(models.Model):
    STATUS_CHOICES = [
        ('CONFIRMED', 'Confirmed'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    seat = models.OneToOneField(Seat, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=250.00)
    ticket_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CONFIRMED', db_index=True)
    booked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attended_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Set by authorized cinema staff after validating the ticket at entry.',
    )
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    coupon_code = models.CharField(max_length=32, blank=True, default='')
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        ordering = ['-booked_at']
        indexes = [
            models.Index(fields=['booked_at']),
            models.Index(fields=['status', 'booked_at']),
            models.Index(fields=['movie', 'status']),
            models.Index(fields=['theater', 'status']),
            models.Index(fields=['user', 'booked_at']),
        ]

    def __str__(self):
        return f'Booking by {self.user.username} for {self.seat.seat_number} at {self.theater.name}'

    @property
    def is_show_completed(self):
        cutoff = self.movie.get_show_end_cutoff()
        return cutoff is not None and self.theater.time <= cutoff

    def check_in_attendee(self):
        """Record a staff-verified ticket check-in only after the screening ends."""
        if self.status != 'CONFIRMED':
            raise ValueError('Only confirmed bookings can be checked in.')
        if not self.is_show_completed:
            raise ValueError('Check-in for review eligibility is available after the screening ends.')
        if self.attended_at:
            return False
        self.attended_at = timezone.now()
        self.save(update_fields=['attended_at'])
        return True

    def cancel(self, refund=True):
        """Cancels a booking and releases its seat; refund status changes only after provider confirmation."""
        self.status = 'CANCELLED'
        self.cancelled_at = timezone.now()
        self.save()
        if self.seat:
            self.seat.is_booked = False
            self.seat.save(update_fields=['is_booked'])


class Review(models.Model):
    RATING_CHOICES = [
        (1, '1 - Poor'),
        (2, '2 - Fair'),
        (3, '3 - Good'),
        (4, '4 - Very Good'),
        (5, '5 - Excellent'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='movie_reviews')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='reviews')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    review_text = models.TextField()
    is_reported = models.BooleanField(default=False)
    report_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'movie')

    def __str__(self):
        return f"{self.user.username}'s review on {self.movie.get_display_title()} ({self.rating}★)"

    @property
    def is_verified_viewer(self):
        show_end_cutoff = self.movie.get_show_end_cutoff()
        if show_end_cutoff is None:
            return False
        return Booking.objects.filter(
            user_id=self.user_id,
            movie_id=self.movie_id,
            status='CONFIRMED',
            theater__time__lte=show_end_cutoff,
            attended_at__isnull=False,
        ).exists()


class ReviewReport(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='reports')
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='review_reports')
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('review', 'reported_by')

    def __str__(self):
        return f"Report on review #{self.review.id} by {self.reported_by.username}"


class SeatReservation(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('EXPIRED', 'Expired'),
        ('CONVERTED', 'Converted to Booking'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='seat_reservations')
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='reservations')
    seats = models.ManyToManyField(Seat, related_name='reservations')
    seat = models.ForeignKey(Seat, on_delete=models.SET_NULL, null=True, blank=True, related_name='single_reservations')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', db_index=True)
    reservation_token = models.UUIDField(default=uuid.uuid4, unique=True)
    total_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    price_breakdown = models.JSONField(default=dict, blank=True)
    coupon_code = models.CharField(max_length=32, blank=True, default='')
    discount_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Reservation #{self.id} by {self.user.username} - {self.theater.movie.name} ({self.status})"

    def is_active(self):
        return self.status == 'ACTIVE' and self.expires_at > timezone.now()

    def time_remaining_seconds(self):
        if not self.is_active():
            return 0
        diff = int((self.expires_at - timezone.now()).total_seconds())
        return max(0, diff)

    def formatted_time_remaining(self):
        secs = self.time_remaining_seconds()
        mins = secs // 60
        rem_secs = secs % 60
        return f"{mins:02d}:{rem_secs:02d}"

    def get_seats_display(self):
        seat_nums = list(self.seats.values_list('seat_number', flat=True))
        if seat_nums:
            return ", ".join(seat_nums)
        if self.seat:
            return self.seat.seat_number
        return "None"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('CREATED', 'Created'),
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('REFUNDED', 'Refunded'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    reservation = models.ForeignKey(SeatReservation, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_single')
    bookings = models.ManyToManyField(Booking, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    provider = models.CharField(max_length=50, default='STRIPE')
    order_id = models.CharField(max_length=100, db_index=True)
    payment_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    signature = models.CharField(max_length=255, blank=True, null=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CREATED', db_index=True)
    failure_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Payment #{self.id} - {self.order_id} ({self.status}) - ₹{self.amount}"

    def is_successful(self):
        return self.status == 'SUCCESS'


class AdminActivity(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='cinema_admin_activities')
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=80, db_index=True)
    object_id = models.CharField(max_length=80, blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} {self.object_type} {self.object_id} by {self.actor or "unknown"}'


# Alias for Showtime references
Showtime = Theater


class PricingPlan(models.Model):
    DAY_TYPE_CHOICES = [
        ('ALL', 'All Days'),
        ('WEEKDAY', 'Weekday (Mon - Thu)'),
        ('WEEKEND', 'Weekend (Fri - Sun)'),
    ]

    name = models.CharField(max_length=150)
    theatre_name = models.CharField(max_length=255, blank=True, default='', db_index=True, help_text="Target cinema name or empty for all cinemas")
    screen_type = models.CharField(max_length=50, default='ALL', choices=[('ALL', 'All Formats')] + Screen.SCREEN_TYPES)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, null=True, blank=True, related_name='pricing_plans')
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    day_type = models.CharField(max_length=20, choices=DAY_TYPE_CHOICES, default='ALL')
    base_price = models.DecimalField(max_digits=8, decimal_places=2, default=180.00)
    category_prices = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"REGULAR": 180, "PREMIUM": 250, "RECLINER": 350, "VIP": 450, "ACCESSIBLE": 150}'
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_pricing_plans')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', 'name']

    def __str__(self):
        return f"{self.name} ({self.start_date} to {self.end_date})"

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({'end_date': "End date cannot be earlier than start date."})

    def get_category_price(self, seat_type='REGULAR'):
        normalized = (seat_type or 'REGULAR').upper()
        if self.category_prices and isinstance(self.category_prices, dict) and normalized in self.category_prices:
            try:
                return float(self.category_prices[normalized])
            except (ValueError, TypeError):
                pass
        return float(self.base_price)

    @classmethod
    def resolve_plan_for_showtime(cls, showtime):
        """
        Finds the most specific active pricing plan matching a showtime:
        1. Checks date range: start_date <= showtime.time.date() <= end_date
        2. Checks day_type: weekday vs weekend
        3. Priority to exact cinema venue + screen_type + movie matches
        """
        show_date = showtime.time.date()
        weekday = showtime.time.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        day_type = 'WEEKEND' if weekday in [4, 5, 6] else 'WEEKDAY'

        candidates = cls.objects.filter(
            is_active=True,
            start_date__lte=show_date,
            end_date__gte=show_date,
        )

        candidates = candidates.filter(models.Q(day_type='ALL') | models.Q(day_type=day_type))

        best_plan = None
        best_score = -1

        for plan in candidates:
            score = 0
            if plan.movie_id:
                if plan.movie_id == showtime.movie_id:
                    score += 10
                else:
                    continue
            if plan.theatre_name:
                if plan.theatre_name.strip().lower() == (showtime.name or '').strip().lower():
                    score += 5
                else:
                    continue
            if plan.screen_type and plan.screen_type != 'ALL':
                stype = showtime.screen.screen_type if showtime.screen else 'STANDARD'
                if plan.screen_type == stype:
                    score += 3
                else:
                    continue
            if plan.day_type == day_type:
                score += 1

            if score > best_score:
                best_score = score
                best_plan = plan

        return best_plan

    @classmethod
    def resolve_price_for_showtime(cls, showtime, seat_type='REGULAR'):
        plan = cls.resolve_plan_for_showtime(showtime)
        if plan:
            return plan.get_category_price(seat_type)
        return None

    def apply_to_future_showtimes(self, user=None):
        """
        Applies this plan's category prices to all matching future showtimes in its date range.
        Does NOT alter past showtimes or existing bookings.
        """
        start_dt = timezone.make_aware(
            timezone.datetime.combine(self.start_date, timezone.datetime.min.time())
        )
        end_dt = timezone.make_aware(
            timezone.datetime.combine(self.end_date, timezone.datetime.max.time())
        )
        now_dt = timezone.now()
        effective_start = max(start_dt, now_dt)

        qs = Theater.objects.filter(time__range=(effective_start, end_dt), active=True)
        if self.theatre_name:
            qs = qs.filter(name__iexact=self.theatre_name)
        if self.movie_id:
            qs = qs.filter(movie_id=self.movie_id)
        if self.screen_type and self.screen_type != 'ALL':
            qs = qs.filter(screen__screen_type=self.screen_type)

        updated_count = 0
        for show in qs:
            weekday = show.time.weekday()
            is_weekend = weekday in [4, 5, 6]
            if self.day_type == 'WEEKDAY' and is_weekend:
                continue
            if self.day_type == 'WEEKEND' and not is_weekend:
                continue

            old_prices = dict(show.ticket_prices or {})
            merged_prices = dict(self.category_prices or {})
            if not merged_prices:
                merged_prices = {
                    'REGULAR': float(self.base_price),
                    'PREMIUM': round(float(self.base_price) * 1.35, 2),
                    'RECLINER': round(float(self.base_price) * 1.8, 2),
                    'VIP': round(float(self.base_price) * 2.2, 2),
                    'ACCESSIBLE': round(float(self.base_price) * 0.9, 2),
                }
            show.ticket_prices = merged_prices
            show.price = merged_prices.get('REGULAR', float(self.base_price))
            show.save(update_fields=['ticket_prices', 'price'])

            PricingHistory.objects.create(
                plan=self,
                theater=show,
                action='BULK_APPLY',
                changed_by=user,
                old_prices=old_prices,
                new_prices=merged_prices,
                details=f"Applied plan '{self.name}' to showtime #{show.id} ({show.time.strftime('%Y-%m-%d %H:%M')})"
            )
            updated_count += 1

        return updated_count


class PricingHistory(models.Model):
    plan = models.ForeignKey(PricingPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name='history')
    theater = models.ForeignKey(Theater, on_delete=models.SET_NULL, null=True, blank=True, related_name='price_history')
    action = models.CharField(max_length=50)  # 'CREATE_PLAN', 'UPDATE_PLAN', 'BULK_APPLY', 'MANUAL_SHOW_UPDATE'
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    old_prices = models.JSONField(default=dict, blank=True)
    new_prices = models.JSONField(default=dict, blank=True)
    details = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} on {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class CouponDiscount(models.Model):
    DISCOUNT_TYPES = [
        ('PERCENTAGE', 'Percentage (%)'),
        ('FLAT', 'Flat Amount (₹)'),
    ]

    code = models.CharField(max_length=32, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, default='')
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES, default='PERCENTAGE')
    discount_value = models.DecimalField(max_digits=8, decimal_places=2)
    min_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    max_discount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    valid_from = models.DateField(default=timezone.now)
    valid_to = models.DateField()
    usage_limit = models.PositiveIntegerField(default=100)
    times_used = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Coupon {self.code} ({self.discount_value}{'%' if self.discount_type == 'PERCENTAGE' else '₹'})"

    def is_valid_now(self, amount=0):
        today = timezone.now().date()
        if not self.active:
            return False, "This coupon is inactive."
        if today < self.valid_from or today > self.valid_to:
            return False, "This coupon is expired or not yet active."
        if self.times_used >= self.usage_limit:
            return False, "This coupon usage limit has been reached."
        if amount and float(amount) < float(self.min_amount):
            return False, f"Minimum booking amount for this coupon is ₹{self.min_amount}."
        return True, ""

    def calculate_discount(self, total_amount):
        amt = float(total_amount)
        valid, msg = self.is_valid_now(amt)
        if not valid:
            return 0.0, msg
        if self.discount_type == 'PERCENTAGE':
            disc = amt * (float(self.discount_value) / 100.0)
            if self.max_discount and disc > float(self.max_discount):
                disc = float(self.max_discount)
        else:
            disc = float(self.discount_value)
        disc = min(amt, max(0.0, disc))
        return round(disc, 2), "Applied successfully"

