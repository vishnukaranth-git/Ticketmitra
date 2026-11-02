from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone

from movies.models import Booking, Movie, Payment
from movies.services.location_service import (
    SUPPORTED_CITIES,
    get_nearby_theaters_and_movies,
)

from .forms import UserRegisterForm, UserUpdateForm


def home(request):
    today = timezone.now().date()
    now = timezone.now()

    # 1. Location-based discovery & 30 km theater radius
    selected_lang = request.GET.get('lang', '').strip().lower()
    discovery_data = get_nearby_theaters_and_movies(request, language_code=selected_lang if selected_lang else None)

    nearby_theaters = discovery_data['theaters']
    user_location = discovery_data['user_location']
    radius_km = discovery_data['radius_km']
    total_theaters = discovery_data['total_theaters']

    # 2. Query ONLY the curated active TMDB catalog (~25-30 movies) excluding OTT-only titles
    city_name = (user_location.get('city') if user_location else None) or 'Bengaluru'
    active_catalog = (
        Movie.objects.filter(is_in_active_catalog=True, is_ott_only=False)
        .prefetch_related('genres', 'languages', 'theaters')
        .annotate(
            active_future_showtimes_count=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__city__iexact=city_name, theaters__time__gte=now)
            ),
            all_active_future_showtimes_count=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__time__gte=now)
            )
        )
    )
    
    # Fallback to any current/upcoming movies if sync hasn't run yet
    if not active_catalog.exists():
        active_catalog = (
            Movie.objects.filter(is_ott_only=False)
            .filter(Q(status='CURRENT') | Q(status='UPCOMING') | Q(status='ADVANCE_BOOKING') | Q(release_date__gte=today - timezone.timedelta(days=60)))
            .prefetch_related('genres', 'languages', 'theaters')
            .annotate(
                active_future_showtimes_count=Count(
                    'theaters',
                    filter=Q(theaters__active=True, theaters__city__iexact=city_name, theaters__time__gte=now)
                ),
                all_active_future_showtimes_count=Count(
                    'theaters',
                    filter=Q(theaters__active=True, theaters__time__gte=now)
                )
            )[:30]
        )

    movies_unavailable = not active_catalog.exists()

    # 3. Released This Week: Indian release date in current calendar week (Monday to Sunday)
    start_of_week = today - timezone.timedelta(days=today.weekday())
    end_of_week = start_of_week + timezone.timedelta(days=6)
    released_this_week_movies = list(
        active_catalog.filter(
            release_date__range=(start_of_week, end_of_week),
            is_ott_only=False
        ).order_by('-popularity', '-release_date')
    )
    if len(released_this_week_movies) < 4:
        recent_extra = list(
            active_catalog.filter(
                release_date__gte=today - timezone.timedelta(days=14),
                release_date__lte=end_of_week,
                is_ott_only=False
            ).exclude(id__in=[m.id for m in released_this_week_movies])
            .order_by('-popularity', '-release_date')[:6]
        )
        released_this_week_movies.extend(recent_extra)

    # 3b. Now Showing: verified theatrical release_date <= today AND has active bookable showtimes
    now_showing_qs = active_catalog.filter(
        release_date__lte=today,
        active_future_showtimes_count__gt=0
    ).order_by('-popularity', '-release_date')

    # If the user's specific city has no showtimes, fall back to all active partner screenings
    if not now_showing_qs.exists():
        now_showing_qs = active_catalog.filter(
            release_date__lte=today,
            all_active_future_showtimes_count__gt=0
        ).order_by('-popularity', '-release_date')

    # If still empty, fall back to CURRENT active catalog titles
    if not now_showing_qs.exists():
        now_showing_qs = active_catalog.filter(
            Q(status='CURRENT') | Q(release_date__lte=today)
        ).order_by('-popularity', '-release_date')

    if selected_lang:
        filtered_by_lang = [
            m for m in now_showing_qs
            if m.original_language == selected_lang or any(l.code == selected_lang for l in m.languages.all())
        ]
        now_showing_movies = filtered_by_lang if filtered_by_lang else list(now_showing_qs)
    else:
        now_showing_movies = list(now_showing_qs)

    # Intelligent Demand Ranking & 3-Category Discovery:
    # A. TRENDING & BOOKING OPEN (Most anticipated high-demand releases with active bookings)
    # B. UPCOMING ANTICIPATED MOVIES (Major upcoming theatrical releases, COMING SOON)
    # C. NOW SHOWING (Other running theatrical movies with active showtimes)
    from movies.services.ranking_service import get_categorized_movies
    from movies.services.weekly_sync_service import get_current_friday_cycle

    cycle_info = get_current_friday_cycle(today)
    categorized_data = get_categorized_movies(
        city=city_name,
        language_code=selected_lang,
        now_dt=now,
    )
    trending_booking_open = categorized_data['trending_booking_open']
    upcoming_anticipated = categorized_data['upcoming_anticipated']
    now_showing_movies = categorized_data['now_showing']
    homepage_movies = trending_booking_open
    released_this_week_ids = {m.id for m in trending_booking_open if m.demand_badge in ('NEW RELEASE', 'ADVANCE OPEN')}

    # 3c. Advance Booking: verified release_date > today AND confirmed advance booking available
    advance_booking_movies = list(
        active_catalog.filter(
            Q(release_date__gt=today) &
            (Q(active_future_showtimes_count__gt=0) | Q(all_active_future_showtimes_count__gt=0) | Q(is_advance_booking_open=True) | Q(status='ADVANCE_BOOKING'))
        ).order_by('release_date', '-popularity')[:12]
    )

    # 3d. Coming Soon / Upcoming: verified release_date > today
    coming_soon_movies = list(
        active_catalog.filter(
            release_date__gt=today,
            active_future_showtimes_count=0,
            is_advance_booking_open=False
        ).exclude(status='ADVANCE_BOOKING').order_by('release_date', '-popularity')[:12]
    )

    # 3e. Now Streaming (OTT Releases in India)
    now_streaming_movies = list(
        Movie.objects.filter(is_in_active_catalog=True)
        .filter(Q(has_ott_release=True) | Q(is_ott_only=True) | Q(status='OTT_ONLY'))
        .order_by('-popularity', '-release_date')[:12]
    )

    # 3d. Recent Theatrical Releases (Within last 14 days, prioritizing active local showtimes)
    fourteen_days_ago = today - timezone.timedelta(days=14)
    recent_theatrical_releases = list(
        active_catalog.filter(
            release_date__gte=fourteen_days_ago,
            release_date__lte=today
        ).order_by('-active_future_showtimes_count', '-release_date', '-popularity')[:12]
    )

    # 4. Trending Now: ordered by real TMDB popularity
    trending_movies = list(active_catalog.order_by('-popularity'))[:12]

    # 5. Upcoming: all future releases ordered nearest first
    upcoming_movies = list(
        active_catalog.filter(release_date__gt=today).order_by('release_date')[:12]
    )

    # 6. South Indian Cinema (Filtered from real active TMDB dataset)
    def get_regional(code):
        return [
            m for m in active_catalog
            if m.original_language == code or any(l.code == code for l in m.languages.all())
        ][:8]

    kannada_movies = get_regional('kn')
    tamil_movies = get_regional('ta')
    telugu_movies = get_regional('te')
    malayalam_movies = get_regional('ml')
    hindi_movies = get_regional('hi')
    english_movies = get_regional('en')

    # 7. Recently Added / Discovery
    recently_added = list(active_catalog.order_by('-created_at', '-release_date'))[:8]

    # 8. Featured Movie: Pick top trending movie with a landscape backdrop
    featured_movie = None
    for m in trending_movies:
        if m.backdrop_url and m.status == 'CURRENT':
            featured_movie = m
            break
    if not featured_movie and trending_movies:
        featured_movie = trending_movies[0]

    from movies.models import Screen
    live_screens_count = Screen.objects.filter(active=True).count() or 44

    # Format cinemas around you for Bengaluru cluster
    cinemas_around_you = [
        {
            'name': 'INOX Galleria Mall',
            'sub': 'Yelahanka Rd • 2.8 km away',
            'badges': ['IMAX', 'Standard'],
            'color': '#EF4444',
            'bg': 'rgba(239, 68, 68, 0.15)',
        },
        {
            'name': 'PVR Vega City',
            'sub': 'Bannerghatta Rd • 5.3 km away',
            'badges': ['4DX', 'PVR LUXE'],
            'color': '#F59E0B',
            'bg': 'rgba(245, 158, 11, 0.15)',
        },
        {
            'name': 'Cinépolis Nexus Mall',
            'sub': 'Koramangala 7th • 7.1 km away',
            'badges': ['Dolby Atmos', 'VIP'],
            'color': '#EAB308',
            'bg': 'rgba(234, 179, 8, 0.15)',
        },
    ]

    # 9. Top Movies This Week (Dynamic Ranked Row - Top 5 Real TMDB Theatrical Releases)
    top_movies_qs = active_catalog.filter(
        is_ott_only=False,
        status='CURRENT',
        tmdb_id__isnull=False,
    )
    if selected_lang:
        top_lang_qs = top_movies_qs.filter(
            Q(original_language=selected_lang) | Q(languages__code=selected_lang)
        ).distinct()
        if top_lang_qs.exists():
            top_movies_qs = top_lang_qs

    top_movies_this_week = list(
        top_movies_qs.order_by('-popularity', '-rating')[:5]
    )
    if len(top_movies_this_week) < 5:
        existing_ids = [m.id for m in top_movies_this_week]
        filler_qs = active_catalog.filter(is_ott_only=False).exclude(id__in=existing_ids)
        if selected_lang:
            filler_lang = filler_qs.filter(
                Q(original_language=selected_lang) | Q(languages__code=selected_lang)
            ).distinct()
            if filler_lang.exists():
                filler_qs = filler_lang
        filler = list(
            filler_qs.order_by('-popularity', '-rating')[:5 - len(top_movies_this_week)]
        )
        top_movies_this_week.extend(filler)

    top_movies_ranking_criterion = 'popularity'

    return render(request, 'home.html', {
        'movies': now_showing_movies[:12],

        'friday_cycle_label': f"Friday Release Cycle ({cycle_info['current_friday'].strftime('%b %d')} – {cycle_info['cycle_end'].strftime('%b %d, %Y')})",

        'is_friday_cycle': cycle_info['is_friday'],

        'trending_booking_open': trending_booking_open,

        'upcoming_anticipated': upcoming_anticipated,

        'total_trending_open': categorized_data['total_trending_open'],

        'total_upcoming': categorized_data['total_upcoming'],

        'total_now_showing': categorized_data['total_now_showing'],
        'now_showing_movies': now_showing_movies,
        'released_this_week_movies': released_this_week_movies,
        'homepage_movies': homepage_movies,
        'released_this_week_ids': released_this_week_ids,
        'now_streaming_movies': now_streaming_movies,
        'advance_booking_movies': advance_booking_movies,
        'coming_soon_movies': coming_soon_movies,
        'recent_theatrical_releases': recent_theatrical_releases,
        'trending_movies': trending_movies,
        'upcoming_movies': upcoming_movies,
        'top_movies_this_week': top_movies_this_week,
        'top_movies_ranking_criterion': top_movies_ranking_criterion,
        'kannada_movies': kannada_movies,
        'tamil_movies': tamil_movies,
        'telugu_movies': telugu_movies,
        'malayalam_movies': malayalam_movies,
        'hindi_movies': hindi_movies,
        'english_movies': english_movies,
        'recently_added': recently_added,
        'featured_movie': featured_movie,
        'movies_unavailable': movies_unavailable,
        'cinemas_around_you': cinemas_around_you,
        'live_screens_count': live_screens_count,
        'nearby_theaters': nearby_theaters,
        'user_location': user_location,
        'radius_km': radius_km,
        'total_theaters': total_theaters,
        'supported_cities': SUPPORTED_CITIES,
        'selected_language': selected_lang,
    })


def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('profile')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        next_url = request.GET.get('next') or request.POST.get('next') or '/'
        return redirect(next_url)

    if request.method == 'POST':
        post_data = request.POST.copy()
        raw_username = post_data.get('username', '').strip()
        if '@' in raw_username:
            try:
                user_match = User.objects.filter(email__iexact=raw_username).first()
                if user_match:
                    post_data['username'] = user_match.username
            except Exception:
                pass

        form = AuthenticationForm(request, data=post_data)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get('next') or request.POST.get('next') or '/'
            return redirect(next_url)
    else:
        form = AuthenticationForm()

    return render(request, 'users/login.html', {
        'form': form,
        'next': request.GET.get('next', ''),
    })


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('home')


@login_required
def profile(request):
    bookings = Booking.objects.filter(user=request.user).select_related('movie', 'theater', 'seat').order_by('-booked_at')
    payments = Payment.objects.filter(user=request.user).select_related('booking', 'booking__movie').order_by('-created_at')[:5]
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        if u_form.is_valid():
            u_form.save()
            return redirect('profile')
    else:
        u_form = UserUpdateForm(instance=request.user)

    return render(request, 'users/profile.html', {
        'u_form': u_form,
        'bookings': bookings,
        'payments': payments,
    })


@login_required
def reset_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'users/reset_password.html', {'form': form})
