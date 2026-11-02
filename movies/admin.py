from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Booking,
    CastMember,
    CouponDiscount,
    Genre,
    Language,
    Movie,
    MoviePoster,
    Payment,
    PricingHistory,
    PricingPlan,
    Review,
    ReviewReport,
    Screen,
    Seat,
    SeatReservation,
    Theater,
)


class SeatInline(admin.TabularInline):
    model = Seat
    extra = 0
    fields = ['seat_number', 'row', 'seat_type', 'is_booked', 'is_blocked']
    readonly_fields = ['is_booked']
    can_delete = True
    show_change_link = True
    classes = ['collapse']


class MoviePosterInline(admin.TabularInline):
    model = MoviePoster
    extra = 1
    fields = ['image', 'image_url', 'is_primary', 'created_at']
    readonly_fields = ['created_at']


class TheaterInline(admin.TabularInline):
    model = Theater
    extra = 1
    fields = ['name', 'screen', 'time', 'city', 'active']


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'tmdb_id']
    search_fields = ['name']


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']
    search_fields = ['name', 'code']


@admin.register(CastMember)
class CastMemberAdmin(admin.ModelAdmin):
    list_display = ['name', 'character', 'tmdb_id']
    search_fields = ['name', 'character']


@admin.register(MoviePoster)
class MoviePosterAdmin(admin.ModelAdmin):
    list_display = ['get_thumbnail', 'movie', 'is_primary', 'created_at']
    list_filter = ['is_primary', 'created_at']
    search_fields = ['movie__title', 'movie__name']

    @admin.display(description="Poster")
    def get_thumbnail(self, obj):
        url = obj.get_url()
        if url:
            return format_html('<img src="{}" style="width: 38px; height: 54px; object-fit: cover; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.4);" />', url)
        return "-"


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['get_poster_thumb', 'get_display_title', 'status_badge', 'original_language', 'get_genres_display', 'runtime_display', 'release_date', 'get_rating_display', 'popularity']
    list_filter = ['status', 'original_language', 'release_date', 'genres']
    search_fields = ['name', 'title', 'original_title', 'cast', 'description']
    inlines = [MoviePosterInline, TheaterInline]
    readonly_fields = ['created_at', 'updated_at', 'popularity', 'vote_count']
    actions = ['sync_selected_from_tmdb', 'update_release_statuses_action']
    fieldsets = (
        ("Movie Information", {
            'fields': (('name', 'title'), ('original_title', 'original_language'), ('release_date', 'runtime'), ('status', 'age_certification'), 'description', 'cast')
        }),
        ("Media & Visuals", {
            'fields': (('image', 'poster_url'), ('backdrop', 'backdrop_url'), 'trailer_url')
        }),
        ("Classification & Cast", {
            'fields': ('genres', 'languages', 'cast_members')
        }),
        ("Ratings & Popularity (TMDB)", {
            'fields': (('tmdb_id', 'rating', 'tmdb_rating'), ('popularity', 'vote_count'), ('created_at', 'updated_at'))
        }),
    )

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('import-tmdb/', self.admin_site.admin_view(self.import_tmdb_view), name='movies_movie_import_tmdb'),
            path('sync-all-tmdb/', self.admin_site.admin_view(self.sync_all_tmdb_view), name='movies_movie_sync_all_tmdb'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        from django.urls import reverse
        extra_context = extra_context or {}
        extra_context['sync_all_tmdb_url'] = reverse('admin:movies_movie_sync_all_tmdb')
        extra_context['import_tmdb_url'] = reverse('admin:movies_movie_import_tmdb')
        return super().changelist_view(request, extra_context=extra_context)

    def sync_all_tmdb_view(self, request):
        """Admin view: trigger full TMDB sync for now-playing + upcoming movies."""
        from django.contrib import messages
        from django.core.management import call_command
        from django.shortcuts import redirect
        try:
            call_command('sync_tmdb_movies', '--all', '--pages=2')
            messages.success(
                request,
                "✅ TMDB sync completed! Now-playing and upcoming movies have been updated from TMDB."
            )
        except Exception as e:
            messages.error(request, f"❌ TMDB sync failed: {e}")
        return redirect('admin:movies_movie_changelist')

    @admin.action(description="🔄 Sync selected movies from TMDB (refresh metadata)")
    def sync_selected_from_tmdb(self, request, queryset):
        from django.contrib import messages

        from movies.services.tmdb_service import TMDBService
        tmdb = TMDBService()
        success_count = 0
        error_count = 0
        for movie in queryset.filter(tmdb_id__isnull=False):
            try:
                tmdb.import_or_update_movie(movie.tmdb_id)
                success_count += 1
            except Exception as exc:
                error_count += 1
                self.message_user(
                    request,
                    f"Error syncing '{movie.get_display_title()}': {exc}",
                    level=messages.ERROR,
                )
        if success_count:
            self.message_user(
                request,
                f"✅ Successfully refreshed {success_count} movie(s) from TMDB.",
                level=messages.SUCCESS,
            )
        if error_count:
            self.message_user(
                request,
                f"⚠️ {error_count} movie(s) could not be synced (no TMDB ID or API error).",
                level=messages.WARNING,
            )

    @admin.action(description="📊 Update release statuses from actual screening schedule")
    def update_release_statuses_action(self, request, queryset):
        from django.contrib import messages
        from django.utils import timezone
        now = timezone.now()
        today = now.date()
        updated = 0
        for movie in queryset.filter(is_ott_only=False):
            has_future = movie.theaters.filter(active=True, time__gte=now).exists()
            if movie.release_date and movie.release_date > today:
                new_status = 'ADVANCE_BOOKING' if (movie.is_advance_booking_open or movie.status == 'ADVANCE_BOOKING') else 'UPCOMING'
            elif has_future:
                new_status = 'CURRENT'
            elif movie.status in ('CURRENT', 'ADVANCE_BOOKING'):
                new_status = 'ENDED'
            else:
                continue  # Already correct or special status
            if movie.status != new_status:
                movie.status = new_status
                movie.save(update_fields=['status'])
                updated += 1
        self.message_user(
            request,
            f"📊 Updated release status for {updated} movie(s) based on actual screening schedule.",
            level=messages.SUCCESS,
        )

    def import_tmdb_view(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.template.response import TemplateResponse

        from movies.services.tmdb_service import TMDBService

        tmdb = TMDBService()
        query = request.GET.get('q', '').strip()
        results = []

        if request.method == 'POST':
            tmdb_id = request.POST.get('import_tmdb_id')
            if tmdb_id:
                try:
                    movie, created = tmdb.import_or_update_movie(int(tmdb_id))
                    action_verb = "imported" if created else "updated"
                    messages.success(request, f'Successfully {action_verb} "{movie.get_display_title()}" from TMDB (Status: {movie.status}).')
                    return redirect('admin:movies_movie_change', movie.id)
                except Exception as e:
                    messages.error(request, f'Failed to import movie: {e!s}')
            return redirect(request.get_full_path())

        if query:
            res = tmdb.search_movies(query)
            results = res.get('results', [])

        existing_tmdb_ids = set(Movie.objects.filter(tmdb_id__isnull=False).values_list('tmdb_id', flat=True))

        context = {
            **self.admin_site.each_context(request),
            'title': 'Search & Import Movie from TMDB',
            'query': query,
            'results': results,
            'existing_tmdb_ids': existing_tmdb_ids,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/movies/movie/import_tmdb.html', context)

    @admin.display(description="Poster")
    def get_poster_thumb(self, obj):
        url = obj.get_poster_url()
        return format_html('<img src="{}" style="width: 44px; height: 62px; object-fit: cover; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15); box-shadow: 0 4px 10px rgba(0,0,0,0.5);" />', url)

    @admin.display(description="Status")
    def status_badge(self, obj):
        variants = {
            'CURRENT': 'success',
            'ENDED': 'danger',
            'DRAFT': 'warning',
        }
        variant = variants.get(obj.status, 'muted')
        return format_html('<span class="tm-badge tm-badge-{}">{}</span>', variant, obj.get_status_display())

    @admin.display(description="Runtime")
    def runtime_display(self, obj):
        return obj.get_runtime_display() or "-"

    @admin.display(description="Rating")
    def get_rating_display(self, obj):
        r = obj.rating or obj.tmdb_rating
        if r:
            return format_html('<span style="color: #F59E0B; font-weight: 700;"><i class="fas fa-star mr-1"></i>{}</span>', r)
        return "-"

    @admin.display(description="Genres")
    def get_genres_display(self, obj):
        genres = [g.name for g in obj.genres.all()[:3]]
        return ", ".join(genres) if genres else "-"


@admin.register(Screen)
class ScreenAdmin(admin.ModelAdmin):
    list_display = ['theater_name', 'name', 'screen_type_badge', 'capacity', 'active_badge', 'get_seats_count', 'screen_actions']
    list_filter = ['screen_type', 'active', 'theater_name']
    search_fields = ['name', 'theater_name', 'screen_type']
    inlines = [SeatInline]

    @admin.display(description="Type")
    def screen_type_badge(self, obj):
        colors = {
            'IMAX': '#E63946',
            '4DX': '#FF7A18',
            'PXL': '#3B82F6',
            'GOLD': '#F59E0B',
            'MX4D': '#8B5CF6',
            'STANDARD': '#64748b'
        }
        color = colors.get(obj.screen_type, '#3B82F6')
        return format_html('<span style="background: rgba(255,255,255,0.08); border: 1px solid {}; color: {}; padding: 3px 8px; border-radius: 6px; font-weight: 700; font-size: 11px;">{}</span>', color, color, obj.screen_type)

    @admin.display(description="Status")
    def active_badge(self, obj):
        if obj.active:
            return format_html('<span class="tm-badge tm-badge-success">Active</span>')
        return format_html('<span class="tm-badge tm-badge-danger">Inactive</span>')

    @admin.display(description="Seats")
    def get_seats_count(self, obj):
        return obj.seats.count()

    @admin.display(description="Actions")
    def screen_actions(self, obj):
        seats_url = reverse('admin_manage_seats_screen', kwargs={'screen_id': obj.id})
        detail_url = reverse('admin_screen_detail', kwargs={'screen_id': obj.id})
        return format_html(
            '<a href="{}" class="tm-btn tm-btn-secondary" style="padding: 3px 8px; font-size: 11px; margin-right: 5px;"><i class="fas fa-chair"></i> Seats</a>'
            '<a href="{}" class="tm-btn tm-btn-ghost" style="padding: 3px 8px; font-size: 11px;"><i class="fas fa-tv"></i> View</a>',
            seats_url, detail_url
        )


@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'screen_info', 'movie_title', 'formatted_time', 'city', 'geo_coordinates', 'active_status', 'available_seats', 'theater_actions']
    list_filter = ['active', 'city', 'screen__screen_type', 'time', 'movie']
    search_fields = ['name', 'location', 'city', 'address', 'movie__title', 'movie__name', 'screen__name']
    inlines = [SeatInline]
    fieldsets = (
        ("Showtime & Screening", {
            'fields': (('name', 'screen'), ('movie', 'time'), ('price', 'active'))
        }),
        ("THEATER LOCATION", {
            'fields': ('address', ('city', 'state'), 'pincode', ('latitude', 'longitude'), 'location'),
            'description': "Configure venue physical address and geographical coordinates for 30 km radius discovery."
        }),
    )

    @admin.display(description="Coordinates")
    def geo_coordinates(self, obj):
        if obj.latitude is not None and obj.longitude is not None:
            return format_html('<small style="color: #93c5fd;"><i class="fas fa-map-marker-alt text-danger mr-1"></i>{}, {}</small>', obj.latitude, obj.longitude)
        return format_html('<small class="text-muted">Not Set</small>')

    @admin.display(description="Screen")
    def screen_info(self, obj):
        if obj.screen:
            return format_html('<span>{} <small style="color: var(--tm-text-muted);">({})</small></span>', obj.screen.name, obj.screen.screen_type)
        return "-"

    @admin.display(description="Movie")
    def movie_title(self, obj):
        return obj.movie.get_display_title()

    @admin.display(description="Showtime")
    def formatted_time(self, obj):
        return obj.time.strftime('%b %d, %Y - %I:%M %p')

    @admin.display(description="Status")
    def active_status(self, obj):
        if obj.active:
            return format_html('<span class="tm-badge tm-badge-success">Active</span>')
        return format_html('<span class="tm-badge tm-badge-danger">Inactive</span>')

    @admin.display(description="Availability")
    def available_seats(self, obj):
        total = obj.seats.count()
        avail = obj.seats.filter(is_booked=False, is_blocked=False).count()
        pct = int(avail / total * 100) if total > 0 else 0
        color = '#22C55E' if pct > 50 else ('#F59E0B' if pct > 20 else '#EF4444')
        return format_html('<strong style="color: {};">{} / {}</strong>', color, avail, total)

    @admin.display(description="Actions")
    def theater_actions(self, obj):
        seats_url = reverse('admin_manage_seats_theater', kwargs={'theater_id': obj.id})
        theater_url = reverse('admin_theater_detail', kwargs={'theater_id': obj.id})
        return format_html(
            '<a href="{}" class="tm-btn tm-btn-secondary" style="padding: 3px 8px; font-size: 11px; margin-right: 5px;"><i class="fas fa-chair"></i> Seats</a>'
            '<a href="{}" class="tm-btn tm-btn-ghost" style="padding: 3px 8px; font-size: 11px;"><i class="fas fa-building"></i> View</a>',
            seats_url, theater_url
        )


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['seat_number', 'row', 'type_badge', 'theater_name', 'screen_name', 'status_badge']
    list_filter = ['is_booked', 'is_blocked', 'seat_type', 'theater__name', 'screen__screen_type']
    search_fields = ['seat_number', 'row', 'theater__name', 'screen__name']
    actions = ['block_selected_seats', 'unblock_selected_seats']

    @admin.action(description="Block Selected Seats (Admin Block)")
    def block_selected_seats(self, request, queryset):
        booked_count = queryset.filter(is_booked=True).count()
        updatable = queryset.filter(is_booked=False)
        updated = updatable.update(is_blocked=True)
        msg = f"Successfully blocked {updated} seat(s). Users cannot reserve or book them."
        if booked_count > 0:
            msg += f" (Note: {booked_count} already booked seat(s) could not be modified)."
        self.message_user(request, msg)

    @admin.action(description="Unblock Selected Seats (Make Available)")
    def unblock_selected_seats(self, request, queryset):
        updated = queryset.update(is_blocked=False)
        self.message_user(request, f"Successfully unblocked {updated} seat(s). They are now Available.")

    @admin.display(description="Theater")
    def theater_name(self, obj):
        return obj.theater.name

    @admin.display(description="Screen")
    def screen_name(self, obj):
        return obj.screen.name if obj.screen else "-"

    @admin.display(description="Type")
    def type_badge(self, obj):
        color = '#3B82F6' if obj.seat_type == 'VIP' else ('#FF7A18' if obj.seat_type == 'PREMIUM' else '#64748b')
        return format_html('<span style="color: {}; font-weight: 600; font-size: 11px;">{}</span>', color, obj.seat_type)

    @admin.display(description="Status")
    def status_badge(self, obj):
        if obj.is_booked:
            return format_html('<span class="tm-badge tm-badge-danger">Booked</span>')
        if getattr(obj, 'is_blocked', False):
            return format_html('<span class="tm-badge tm-badge-muted">Blocked</span>')
        return format_html('<span class="tm-badge tm-badge-success">Available</span>')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'user_info', 'movie_title', 'theater_info', 'seat_number', 'amount_formatted', 'status_badge', 'attendance_badge', 'booked_at_formatted', 'actions_column']
    list_filter = ['status', 'booked_at', 'theater']
    search_fields = ['id', 'user__username', 'user__email', 'movie__title', 'movie__name', 'theater__name', 'seat__seat_number']
    readonly_fields = ['attended_at']
    actions = ['check_in_selected_bookings', 'cancel_selected_bookings']

    @admin.display(description="Customer")
    def user_info(self, obj):
        return format_html('<strong>{}</strong> <small style="color: var(--tm-text-muted);">({})</small>', obj.user.username, obj.user.email or "no email")

    @admin.display(description="Movie")
    def movie_title(self, obj):
        return obj.movie.get_display_title()

    @admin.display(description="Theater")
    def theater_info(self, obj):
        return obj.theater.name

    @admin.display(description="Seat")
    def seat_number(self, obj):
        return format_html('<span class="tm-badge tm-badge-blue">Seat {}</span>', obj.seat.seat_number)

    @admin.display(description="Amount")
    def amount_formatted(self, obj):
        return format_html('<strong style="color: #22C55E;">₹{}</strong>', obj.amount)

    @admin.display(description="Status")
    def status_badge(self, obj):
        if obj.status == 'CONFIRMED':
            return format_html('<span class="tm-badge tm-badge-success">Confirmed</span>')
        return format_html('<span class="tm-badge tm-badge-danger">Cancelled</span>')

    @admin.display(description="Attendance")
    def attendance_badge(self, obj):
        if obj.attended_at:
            return format_html('<span class="tm-badge tm-badge-success">Checked in</span>')
        return format_html('<span class="tm-badge tm-badge-muted">Not checked in</span>')

    @admin.display(description="Booked At")
    def booked_at_formatted(self, obj):
        return obj.booked_at.strftime('%Y-%m-%d %I:%M %p')

    @admin.display(description="Ticket")
    def actions_column(self, obj):
        ticket_url = reverse('booking_ticket', kwargs={'booking_id': obj.id})
        return format_html('<a href="{}" target="_blank" class="tm-btn tm-btn-ghost" style="padding: 3px 8px; font-size: 11px;"><i class="fas fa-ticket-alt"></i> Ticket</a>', ticket_url)

    @admin.action(description="Check in selected confirmed bookings for completed shows")
    def check_in_selected_bookings(self, request, queryset):
        count = 0
        for booking in queryset.select_related('movie', 'theater'):
            try:
                if booking.check_in_attendee():
                    count += 1
            except ValueError:
                continue
        self.message_user(request, f"Checked in {count} eligible booking(s).")

    @admin.action(description="Cancel selected bookings and release seats")
    def cancel_selected_bookings(self, request, queryset):
        count = 0
        for b in queryset.filter(status='CONFIRMED'):
            b.cancel(refund=True)
            count += 1
        self.message_user(request, f"Successfully cancelled {count} booking(s) and released associated seat(s).")


@admin.register(SeatReservation)
class SeatReservationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'get_movie', 'theater', 'get_seats_display',
        'status_badge', 'total_amount_formatted', 'created_at', 'expires_at', 'time_left'
    ]
    list_filter = ['status', 'theater', 'theater__movie', 'created_at', 'expires_at']
    search_fields = [
        'user__username', 'theater__name', 'theater__movie__title',
        'theater__movie__name', 'seats__seat_number', 'reservation_token'
    ]
    readonly_fields = ['created_at', 'expires_at', 'reservation_token']
    filter_horizontal = ['seats']

    @admin.display(description="Movie")
    def get_movie(self, obj):
        return obj.theater.movie.get_display_title()

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            'ACTIVE': 'warning',
            'CONVERTED': 'success',
            'EXPIRED': 'muted',
            'CANCELLED': 'danger',
        }
        variant = colors.get(obj.status, 'muted')
        return format_html('<span class="tm-badge tm-badge-{}">{}</span>', variant, obj.status)

    @admin.display(description="Amount")
    def total_amount_formatted(self, obj):
        return f"₹{obj.total_amount}"

    @admin.display(description="Time Left")
    def time_left(self, obj):
        if obj.is_active():
            return format_html('<strong style="color: var(--tm-warning);"><i class="fas fa-stopwatch mr-1"></i>{}</strong>', obj.formatted_time_remaining())
        return "-"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_info', 'amount_formatted', 'provider_badge', 'status_badge',
        'order_id', 'payment_id', 'created_at_formatted'
    ]
    list_filter = ['status', 'provider', 'created_at']
    search_fields = [
        'payment_id', 'order_id', 'transaction_id',
        'user__email', 'user__username'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'order_id', 'payment_id', 'signature', 'transaction_id'
    ]
    filter_horizontal = ['bookings']

    @admin.display(description="Customer")
    def user_info(self, obj):
        return obj.user.username

    @admin.display(description="Amount")
    def amount_formatted(self, obj):
        return format_html('<strong>₹{}</strong>', obj.amount)

    @admin.display(description="Provider")
    def provider_badge(self, obj):
        return format_html('<span style="color: #635bff; font-weight: 700;"><i class="fab fa-stripe mr-1"></i>{}</span>', obj.provider)

    @admin.display(description="Status")
    def status_badge(self, obj):
        badges = {
            'SUCCESS': 'success',
            'PENDING': 'blue',
            'CREATED': 'blue',
            'FAILED': 'danger',
            'CANCELLED': 'danger',
            'REFUNDED': 'purple',
        }
        b = badges.get(obj.status, 'muted')
        return format_html('<span class="tm-badge tm-badge-{}">{}</span>', b, obj.status)

    @admin.display(description="Date")
    def created_at_formatted(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %I:%M %p')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['movie_title', 'user', 'rating_stars', 'verified_badge', 'report_status', 'created_at']
    list_filter = ['rating', 'is_reported', 'created_at']
    search_fields = ['movie__title', 'movie__name', 'user__username', 'review_text']
    readonly_fields = ['created_at', 'updated_at']

    @admin.display(description="Movie")
    def movie_title(self, obj):
        return obj.movie.get_display_title()

    @admin.display(description="Rating")
    def rating_stars(self, obj):
        stars = "★" * obj.rating + "☆" * (5 - obj.rating)
        return format_html('<span style="color: #F59E0B; font-size: 13px;">{}</span>', stars)

    @admin.display(description="Verified")
    def verified_badge(self, obj):
        if obj.is_verified_viewer:
            return format_html('<span class="tm-badge tm-badge-success"><i class="fas fa-check-circle mr-1"></i>Verified</span>')
        return "-"

    @admin.display(description="Reports")
    def report_status(self, obj):
        if obj.is_reported or obj.report_count > 0:
            return format_html('<span class="tm-badge tm-badge-danger"><i class="fas fa-flag mr-1"></i>{} Flagged</span>', obj.report_count)
        return format_html('<span class="tm-badge tm-badge-muted">Clean</span>')


@admin.register(ReviewReport)
class ReviewReportAdmin(admin.ModelAdmin):
    list_display = ['get_movie', 'review_snippet', 'reported_by', 'reason', 'created_at']
    list_filter = ['created_at']
    search_fields = ['review__movie__title', 'reported_by__username', 'reason']
    readonly_fields = ['created_at']

    @admin.display(description="Movie")
    def get_movie(self, obj):
        return obj.review.movie.get_display_title()

    @admin.display(description="Review")
    def review_snippet(self, obj):
        return f"{obj.review.review_text[:40]}..."


@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'theatre_name', 'screen_type', 'start_date', 'end_date', 'day_type', 'base_price', 'is_active']
    list_filter = ['is_active', 'screen_type', 'day_type', 'start_date']
    search_fields = ['name', 'theatre_name']


@admin.register(PricingHistory)
class PricingHistoryAdmin(admin.ModelAdmin):
    list_display = ['action', 'plan', 'theater', 'changed_by', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['details', 'changed_by__username']
    readonly_fields = ['created_at']


@admin.register(CouponDiscount)
class CouponDiscountAdmin(admin.ModelAdmin):
    list_display = ['code', 'discount_type', 'discount_value', 'valid_from', 'valid_to', 'usage_limit', 'times_used', 'active']
    list_filter = ['active', 'discount_type']
    search_fields = ['code', 'description']

