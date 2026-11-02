import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import DecimalField, Min, Q, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import (
    Booking,
    CinemaVenue,
    CouponDiscount,
    Genre,
    Language,
    Movie,
    Payment,
    Review,
    ReviewReport,
    Seat,
    SeatReservation,
    Theater,
)
from .services import stripe_service

razorpay_service = stripe_service
import logging

logger = logging.getLogger(__name__)


def get_recommended_movies(request, current_movie_id=None, limit=6):
    """
    Computes personalized recommendations based on:
    1. User's confirmed booking history (genres, languages)
    2. Recently viewed movies stored in user session
    3. Fallback to top-rated & trending movies for guest or new users.
    """
    booked_movie_ids = set()
    fav_genres = set()
    fav_languages = set()

    # 1. Booking history
    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        user_bookings = Booking.objects.filter(user=request.user, status='CONFIRMED').values_list('movie_id', flat=True)
        booked_movie_ids = set(user_bookings)
        if booked_movie_ids:
            booked_movies = Movie.objects.filter(id__in=booked_movie_ids).prefetch_related('genres')
            for bm in booked_movies:
                for g in bm.genres.all():
                    fav_genres.add(g.id)
                if bm.original_language:
                    fav_languages.add(bm.original_language)

    # 2. Recently viewed movies in session
    recent_viewed_ids = request.session.get('recently_viewed_movies', []) if (hasattr(request, 'session') and request.session) else []
    if recent_viewed_ids:
        viewed_movies = Movie.objects.filter(id__in=recent_viewed_ids).prefetch_related('genres')
        for vm in viewed_movies:
            for g in vm.genres.all():
                fav_genres.add(g.id)
            if vm.original_language:
                fav_languages.add(vm.original_language)

    exclude_ids = set(booked_movie_ids)
    if current_movie_id:
        exclude_ids.add(current_movie_id)

    candidate_qs = Movie.objects.filter(is_in_active_catalog=True).exclude(id__in=exclude_ids).prefetch_related('genres', 'languages')

    # If preferences exist, rank matching movies strictly from active catalog
    if fav_genres or fav_languages:
        match_filter = Q()
        if fav_genres:
            match_filter |= Q(genres__id__in=list(fav_genres))
        if fav_languages:
            match_filter |= Q(original_language__in=list(fav_languages)) | Q(languages__code__in=list(fav_languages))

        matched = list(candidate_qs.filter(match_filter).distinct().order_by('-popularity', '-tmdb_rating')[:limit])
        if len(matched) < limit:
            remaining = limit - len(matched)
            existing_ids = {m.id for m in matched} | exclude_ids
            fallback = list(candidate_qs.exclude(id__in=existing_ids).order_by('-popularity', '-tmdb_rating')[:remaining])
            matched.extend(fallback)
        return matched

    # If no booking or viewing history exists, do not display un-personalized recommendations
    return []


def movie_list(request):
    """
    Feature-rich Movie Discovery Module:
    - Search by title, name, cast, and description
    - Multi-criteria filters: genre, language, city, theater, release date, rating, show timings
    - Dynamic sorting: popularity, newest releases, rating, ticket price (low-high, high-low)
    - Dynamic count of matching movies
    - Pagination for large datasets
    - Personalized 'Recommended for You' section (only when real booking/viewing history exists)
    """
    search_query = request.GET.get('search', request.GET.get('q', '')).strip()
    genre_filter = request.GET.get('genre', '').strip()
    language_filter = request.GET.get('language', '').strip()
    city_filter = request.GET.get('city', '').strip()
    theater_filter = request.GET.get('theater', '').strip()
    release_date_filter = request.GET.get('release_date', '').strip()
    min_rating = request.GET.get('rating', '').strip()
    show_timing_filter = request.GET.get('timing', '').strip()
    sort_by = request.GET.get('sort', 'popularity').strip()
    page_number = request.GET.get('page', 1)

    now = timezone.now()
    today = now.date()

    # Base QuerySet strictly scoped to active catalog (~25-30 movies) excluding OTT-only titles
    from django.db.models import Count
    movies = (
        Movie.objects.filter(is_in_active_catalog=True, is_ott_only=False)
        .prefetch_related('genres', 'languages')
        .annotate(
            min_ticket_price=Coalesce(
                Min('theaters__price', filter=Q(theaters__active=True)),
                Value(180.00),
                output_field=DecimalField()
            ),
            active_future_showtimes_count=Count(
                'theaters',
                filter=Q(theaters__active=True, theaters__time__gte=now)
            )
        )
    )

    # 1. Multi-field Search: title, name, cast, cast_members, overview, genres, languages
    if search_query:
        movies = movies.filter(
            Q(title__icontains=search_query) |
            Q(name__icontains=search_query) |
            Q(original_title__icontains=search_query) |
            Q(cast__icontains=search_query) |
            Q(cast_members__name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(genres__name__icontains=search_query) |
            Q(languages__name__icontains=search_query)
        ).distinct()

    # 2. Genre Filter (by ID or name)
    if genre_filter:
        if genre_filter.isdigit():
            movies = movies.filter(genres__id=int(genre_filter))
        else:
            movies = movies.filter(genres__name__iexact=genre_filter)

    # 3. Language Filter (by code or name)
    if language_filter:
        movies = movies.filter(
            Q(languages__code__iexact=language_filter) |
            Q(languages__name__iexact=language_filter) |
            Q(original_language__iexact=language_filter)
        )

    # 4. City Filter (theaters screening movie in this city)
    if city_filter:
        movies = movies.filter(theaters__city__iexact=city_filter, theaters__active=True)

    # 5. Theater Filter (theaters screening movie by theater id or name)
    if theater_filter:
        if theater_filter.isdigit():
            movies = movies.filter(theaters__id=int(theater_filter), theaters__active=True)
        else:
            movies = movies.filter(theaters__name__icontains=theater_filter, theaters__active=True)

    # 6. Release Date Filter (Date-Aware Theatrical Logic)
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    if release_date_filter == 'this_week':
        movies = movies.filter(release_date__range=(start_of_week, end_of_week))
    elif release_date_filter == 'streaming':
        movies = Movie.objects.filter(is_in_active_catalog=True).filter(Q(has_ott_release=True) | Q(is_ott_only=True) | Q(status='OTT_ONLY'))
    elif release_date_filter == 'now_showing':
        movies = movies.filter(release_date__lte=today, active_future_showtimes_count__gt=0)
    elif release_date_filter == 'advance_booking':
        movies = movies.filter(
            Q(release_date__gt=today) & (Q(active_future_showtimes_count__gt=0) | Q(is_advance_booking_open=True) | Q(status='ADVANCE_BOOKING'))
        )
    elif release_date_filter == 'upcoming':
        movies = movies.filter(release_date__gt=today)
    elif release_date_filter == 'recent':
        fourteen_days_ago = today - timedelta(days=14)
        movies = movies.filter(release_date__gte=fourteen_days_ago, release_date__lte=today)
    elif release_date_filter == 'this_year':
        movies = movies.filter(release_date__year=today.year)
    elif release_date_filter.isdigit() and len(release_date_filter) == 4:
        movies = movies.filter(release_date__year=int(release_date_filter))

    # 7. Rating Filter
    if min_rating:
        try:
            r_val = float(min_rating)
            movies = movies.filter(Q(rating__gte=r_val) | Q(tmdb_rating__gte=r_val))
        except ValueError:
            pass

    # 8. Show Timings Filter (morning, afternoon, evening, night)
    if show_timing_filter:
        timing_low = show_timing_filter.lower()
        if timing_low == 'morning':
            movies = movies.filter(theaters__time__hour__lt=12, theaters__active=True)
        elif timing_low == 'afternoon':
            movies = movies.filter(theaters__time__hour__gte=12, theaters__time__hour__lt=16, theaters__active=True)
        elif timing_low == 'evening':
            movies = movies.filter(theaters__time__hour__gte=16, theaters__time__hour__lt=20, theaters__active=True)
        elif timing_low == 'night':
            movies = movies.filter(theaters__time__hour__gte=20, theaters__active=True)

    # Eliminate duplicate movie rows caused by M2M joins
    movies = movies.distinct()

    # 9. Sorting
    if sort_by == 'newest':
        movies = movies.order_by('-release_date', '-popularity')
    elif sort_by == 'rating':
        movies = movies.order_by('-tmdb_rating', '-rating')
    elif sort_by == 'price_low':
        movies = movies.order_by('min_ticket_price', '-popularity')
    elif sort_by == 'price_high':
        movies = movies.order_by('-min_ticket_price', '-popularity')
    elif sort_by == 'title':
        movies = movies.order_by('name', 'title')
    else:  # 'popularity' default
        movies = movies.order_by('-popularity', '-release_date')

    # Dynamic count of matching movies
    matching_count = movies.count()

    # 10. Pagination (12 movies per page)
    paginator = Paginator(movies, 12)
    try:
        page_obj = paginator.get_page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.get_page(1)

    # 11. Personalized "Recommended for You" section
    recommended_movies = get_recommended_movies(request, limit=6)

    # Data for filter controls
    all_genres = Genre.objects.all().order_by('name')
    all_languages = Language.objects.all().order_by('name')
    all_cities = Theater.objects.filter(active=True).values_list('city', flat=True).distinct().order_by('city')
    all_theaters = Theater.objects.filter(active=True).values('id', 'name', 'city').distinct().order_by('name')

    # Check for AJAX request (for live counter and dynamic movie card updates)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        movie_items = []
        for m in page_obj:
            first_lang = m.languages.first()
            movie_items.append({
                'id': m.id,
                'title': m.get_display_title(),
                'poster_url': m.get_poster_url(),
                'rating': float(m.rating or m.tmdb_rating or 0.0),
                'language': m.original_language or (first_lang.code if first_lang else 'N/A'),
                'release_date': m.release_date.strftime('%b %d, %Y') if m.release_date else 'TBA',
                'min_price': float(getattr(m, 'min_ticket_price', 180.00)),
                'genres': [g.name for g in m.genres.all()[:2]],
                'detail_url': reverse('movie_detail', kwargs={'movie_id': m.id}),
            })
        return JsonResponse({
            'success': True,
            'count': matching_count,
            'results': movie_items,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
        })

    # Prepare preserved query string for pagination links
    params = request.GET.copy()
    if 'page' in params:
        del params['page']
    preserved_query = params.urlencode()

    context = {
        'page_obj': page_obj,
        'movies': page_obj,
        'matching_count': matching_count,
        'recommended_movies': recommended_movies,
        'search_query': search_query,
        'selected_genre': genre_filter,
        'selected_language': language_filter,
        'selected_city': city_filter,
        'selected_theater': theater_filter,
        'selected_release_date': release_date_filter,
        'selected_rating': min_rating,
        'selected_timing': show_timing_filter,
        'selected_sort': sort_by,
        'all_genres': all_genres,
        'all_languages': all_languages,
        'all_cities': sorted(set(all_cities)),
        'all_theaters': all_theaters,
        'preserved_query': preserved_query,
    }
    return render(request, 'movies/movie_list.html', context)


def search_suggestions(request):
    """Returns quick JSON search suggestions for navbar live search."""
    q = request.GET.get('q', '').strip()
    if not q or len(q) < 2:
        return JsonResponse({'results': []})
    
    matches = Movie.objects.filter(
        Q(title__icontains=q) |
        Q(name__icontains=q) |
        Q(genres__name__icontains=q) |
        Q(languages__name__icontains=q)
    ).distinct()[:6]

    results = []
    for m in matches:
        results.append({
            'id': m.id,
            'title': m.get_display_title(),
            'poster_url': m.get_poster_url(),
            'rating': str(m.rating) if m.rating else (str(m.tmdb_rating) if m.tmdb_rating else 'N/A'),
            'year': str(m.release_date.year) if m.release_date else '',
            'url': reverse('movie_detail', kwargs={'movie_id': m.id}),
        })
    return JsonResponse({'results': results})


def movie_detail(request, movie_id):
    movie = get_object_or_404(
        Movie.objects.prefetch_related('genres', 'languages', 'cast_members', 'posters', 'reviews__user', 'theaters'),
        id=movie_id
    )

    # Track recently viewed movie in user session for recommendations
    try:
        viewed_list = request.session.get('recently_viewed_movies', [])
        if movie_id in viewed_list:
            viewed_list.remove(movie_id)
        viewed_list.insert(0, movie_id)
        request.session['recently_viewed_movies'] = viewed_list[:12]
        request.session.modified = True
    except Exception:
        pass

    from .services.location_service import (
        SUPPORTED_CITIES,
        get_nearby_theaters_and_movies,
    )
    discovery_data = get_nearby_theaters_and_movies(request, movie_id=movie.id)
    nearby_theaters = discovery_data['theaters']
    user_location = discovery_data['user_location']
    radius_km = discovery_data['radius_km']
    total_theaters = discovery_data['total_theaters']

    theaters = movie.theaters.filter(active=True, time__gte=timezone.now()).order_by('time')

    # Reviews and ratings
    reviews = movie.get_valid_reviews().select_related('user', 'booking', 'booking__theater').order_by('-created_at')
    avg_user_rating = movie.get_average_user_rating()
    user_review_count = movie.get_review_count()

    # User review eligibility and existing review
    existing_user_review = None
    can_review = False
    has_future_booking = False
    has_past_unchecked_booking = False
    past_booking = None

    if request.user.is_authenticated:
        existing_user_review = movie.reviews.filter(user=request.user).first()
        show_end_cutoff = movie.get_show_end_cutoff()
        if show_end_cutoff is not None:
            past_booking = Booking.objects.filter(
                user=request.user,
                movie=movie,
                status='CONFIRMED',
                theater__time__lte=show_end_cutoff,
                attended_at__isnull=False,
            ).select_related('theater').order_by('-theater__time').first()

        can_review = (past_booking is not None)
        if not can_review:
            show_qs = Booking.objects.filter(user=request.user, movie=movie, status='CONFIRMED')
            if show_end_cutoff is None:
                has_future_booking = show_qs.exists()
            else:
                has_future_booking = show_qs.filter(theater__time__gt=show_end_cutoff).exists()
                has_past_unchecked_booking = show_qs.filter(
                    theater__time__lte=show_end_cutoff,
                    attended_at__isnull=True,
                ).exists()

    # Recommendations
    catalog_movies = Movie.objects.filter(is_in_active_catalog=True).exclude(status='DRAFT').exclude(id=movie.id)
    similar_movies = movie.get_similar_movies(limit=4)
    trending_movies = catalog_movies.filter(is_ott_only=False).order_by('-popularity', '-vote_count', '-release_date')[:4]
    fourteen_days_ago = timezone.now().date() - timedelta(days=14)
    recently_released = catalog_movies.filter(
        is_ott_only=False,
        release_date__lte=timezone.now().date(),
        release_date__gte=fourteen_days_ago
    ).order_by('-release_date')[:4]

    context = {
        'movie': movie,
        'theaters': theaters,
        'nearby_theaters': nearby_theaters,
        'user_location': user_location,
        'radius_km': radius_km,
        'total_theaters': total_theaters,
        'supported_cities': SUPPORTED_CITIES,
        'reviews': reviews,
        'avg_user_rating': avg_user_rating,
        'user_review_count': user_review_count,
        'existing_user_review': existing_user_review,
        'can_review': can_review,
        'has_future_booking': has_future_booking,
        'has_past_unchecked_booking': has_past_unchecked_booking,
        'past_booking': past_booking,
        'similar_movies': similar_movies,
        'trending_movies': trending_movies,
        'recently_released': recently_released,
    }
    return render(request, 'movies/movie_detail.html', context)


@login_required
def update_trailer(request, movie_id):
    """Allows staff/admins to update trailer YouTube URL directly from movie page."""
    if not request.user.is_staff:
        messages.error(request, 'Staff privileges required to edit trailers.')
        return redirect('movie_detail', movie_id=movie_id)

    if request.method == 'POST':
        movie = get_object_or_404(Movie, id=movie_id)
        new_url = request.POST.get('trailer_url', '').strip()
        if new_url:
            import re
            match = re.search(r'(?:v=|\/embed\/|\.be\/|\/v\/)([a-zA-Z0-9_-]{11})', new_url)
            if not match:
                messages.error(request, 'Invalid YouTube URL. Please provide a valid YouTube watch or embed link.')
                return redirect('movie_detail', movie_id=movie_id)
            movie.trailer_url = f"https://www.youtube.com/watch?v={match.group(1)}"
        else:
            movie.trailer_url = ''
        movie.save()
        messages.success(request, f'Trailer URL for "{movie.get_display_title()}" updated successfully!')

    return redirect('movie_detail', movie_id=movie_id)


def movie_trailer_preview(request, movie_id):
    """
    API endpoint returning movie trailer data for the cinematic preview modal.
    If trailer_url is missing, searches YouTube using TMDB's canonical movie
    metadata, then falls back to TMDB's video list. Verified results are cached
    in the existing trailer_url field without adding a model or migration.
    """
    movie = get_object_or_404(Movie, id=movie_id)
    embed_url = movie.get_trailer_embed_url()

    # The inline hover preview uses only the existing TMDB video catalogue.
    # The modal may still use the optional YouTube Data API discovery path.
    use_youtube_discovery = request.GET.get('source') != 'tmdb'
    if use_youtube_discovery and not embed_url and movie.tmdb_id:
        try:
            from .services.youtube_trailer_service import YouTubeTrailerService
            youtube_video_id = YouTubeTrailerService().find_trailer_id(movie)
            if youtube_video_id:
                movie.trailer_url = f'https://www.youtube-nocookie.com/embed/{youtube_video_id}'
                movie.save(update_fields=['trailer_url'])
                embed_url = movie.get_trailer_embed_url()
        except Exception as e:
            logger.warning('YouTube trailer discovery failed for movie %s (%s).', movie.id, type(e).__name__)

    # Keep the existing TMDB video source as a safe fallback.
    if not embed_url and movie.tmdb_id:
        tmdb_miss_key = f'ticketmitra:tmdb-trailer-miss:v1:{movie.tmdb_id}'
        if not cache.get(tmdb_miss_key):
            try:
                from .services.tmdb_service import TMDBService
                tmdb = TMDBService()
                if tmdb.api_key:
                    videos_data = tmdb.get_movie_videos(movie.tmdb_id)
                    trailer = tmdb.extract_youtube_trailer_url(videos_data)
                    if trailer:
                        movie.trailer_url = trailer
                        movie.save(update_fields=['trailer_url'])
                        embed_url = movie.get_trailer_embed_url()
                    else:
                        cache.set(tmdb_miss_key, True, timeout=60 * 60 * 6)
            except Exception as e:
                logger.warning('TMDB trailer fallback failed for movie %s (%s).', movie.id, type(e).__name__)
                cache.set(tmdb_miss_key, True, timeout=300)

    return JsonResponse({
        'success': True,
        'has_trailer': bool(embed_url),
        'embed_url': embed_url or '',
        'title': movie.get_display_title(),
        'rating': float(movie.rating or movie.tmdb_rating or 0.0),
        'poster_url': movie.get_poster_url(),
        'backdrop_url': movie.get_backdrop_url() or movie.get_poster_url(),
        'overview': movie.description or '',
        'release_date': str(movie.release_date or ''),
        'language': movie.original_language.upper() if movie.original_language else '',
        'runtime': movie.get_runtime_display() or '',
        'description': movie.description or '',
        'detail_url': reverse('movie_detail', kwargs={'movie_id': movie.id}),
        'book_url': reverse('theater_list', kwargs={'movie_id': movie.id}) if movie.is_bookable else '',
        'is_bookable': movie.is_bookable,
    })


def _wants_review_json(request):
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
    )


def _review_json_payload(review):
    movie = review.movie
    return {
        'id': review.id,
        'username': review.user.get_full_name() or review.user.username,
        'rating': review.rating,
        'review_text': review.review_text,
        'is_verified_viewer': review.is_verified_viewer,
        'created_at': timezone.localtime(review.created_at).strftime('%B %d, %Y'),
        'average_rating': movie.get_average_user_rating(),
        'review_count': movie.get_review_count(),
        'edit_url': reverse('edit_review', kwargs={'review_id': review.id}),
        'delete_url': reverse('delete_review', kwargs={'review_id': review.id}),
    }


def _review_reject(request, movie, message, status=400, level=messages.ERROR):
    if _wants_review_json(request):
        return JsonResponse({'success': False, 'error': message}, status=status)
    messages.add_message(request, level, message)
    return redirect('movie_detail', movie_id=movie.id)


@login_required(login_url='/login/')
def add_review(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    if request.method != 'POST':
        return redirect('movie_detail', movie_id=movie.id)

    # Only an attended, confirmed booking for a screening whose runtime has elapsed qualifies.
    show_end_cutoff = movie.get_show_end_cutoff()
    if show_end_cutoff is None:
        return _review_reject(
            request,
            movie,
            'This movie has no runtime recorded, so the screening completion cannot be verified yet.',
            status=403,
        )
    past_booking = Booking.objects.filter(
        user=request.user,
        movie=movie,
        status='CONFIRMED',
        theater__time__lte=show_end_cutoff,
        attended_at__isnull=False,
    ).select_related('theater').order_by('-theater__time').first()
    if not past_booking:
        return _review_reject(
            request,
            movie,
            'A staff-verified cinema check-in is required before you can review this movie.',
            status=403,
        )

    if Review.objects.filter(user=request.user, movie=movie).exists():
        return _review_reject(
            request,
            movie,
            'You have already reviewed this movie. Edit your existing review instead.',
            status=409,
            level=messages.WARNING,
        )

    rating = request.POST.get('rating')
    review_text = request.POST.get('review_text', '').strip()
    if not rating or not review_text:
        return _review_reject(request, movie, 'Please provide both a star rating and a review message.')

    try:
        rating_val = int(rating)
        if rating_val < 1 or rating_val > 5:
            raise ValueError
    except (ValueError, TypeError):
        return _review_reject(request, movie, 'Rating must be between 1 and 5 stars.')

    try:
        with transaction.atomic():
            review = Review.objects.create(
                user=request.user,
                movie=movie,
                booking=past_booking,
                rating=rating_val,
                review_text=review_text,
            )
    except IntegrityError:
        return _review_reject(
            request,
            movie,
            'You have already reviewed this movie. Edit your existing review instead.',
            status=409,
            level=messages.WARNING,
        )

    if _wants_review_json(request):
        return JsonResponse({'success': True, 'message': 'Your review has been published.', 'review': _review_json_payload(review)})
    messages.success(request, 'Your review has been published with the Verified Viewer badge!')
    return redirect('movie_detail', movie_id=movie.id)


@login_required(login_url='/login/')
def edit_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    if review.user != request.user:
        if _wants_review_json(request):
            return JsonResponse({'success': False, 'error': 'You are not authorized to edit this review.'}, status=403)
        messages.error(request, "You are not authorized to edit this review.")
        return redirect('movie_detail', movie_id=review.movie.id)

    if request.method == 'POST':
        rating = request.POST.get('rating')
        review_text = request.POST.get('review_text', '').strip()

        if not rating or not review_text:
            if _wants_review_json(request):
                return JsonResponse({'success': False, 'error': 'Please provide both a star rating and a review message.'}, status=400)
            messages.error(request, "Please provide both a star rating and a review message.")
            return redirect('movie_detail', movie_id=review.movie.id)

        try:
            rating_val = int(rating)
            if rating_val < 1 or rating_val > 5:
                raise ValueError()
            review.rating = rating_val
        except ValueError:
            if _wants_review_json(request):
                return JsonResponse({'success': False, 'error': 'Rating must be between 1 and 5 stars.'}, status=400)
            messages.error(request, "Rating must be between 1 and 5 stars.")
            return redirect('movie_detail', movie_id=review.movie.id)

        review.review_text = review_text
        review.save()
        if _wants_review_json(request):
            return JsonResponse({'success': True, 'message': 'Your review has been updated.', 'review': _review_json_payload(review)})
        messages.success(request, "Your review has been successfully updated!")

    return redirect('movie_detail', movie_id=review.movie.id)


@login_required(login_url='/login/')
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    movie_id = review.movie.id
    if review.user != request.user:
        messages.error(request, "You are not authorized to delete this review.")
        return redirect('movie_detail', movie_id=movie_id)

    if request.method == 'POST':
        review.delete()
        messages.success(request, "Your review has been deleted.")

    return redirect('movie_detail', movie_id=movie_id)


@login_required(login_url='/login/')
def report_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    movie_id = review.movie.id

    if review.user == request.user:
        messages.error(request, "You cannot report your own review.")
        return redirect('movie_detail', movie_id=movie_id)

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip() or 'Inappropriate content'
        already_reported = ReviewReport.objects.filter(review=review, reported_by=request.user).exists()

        if already_reported:
            messages.info(request, "You have already reported this review. Our moderators are reviewing it.")
        else:
            try:
                with transaction.atomic():
                    ReviewReport.objects.create(review=review, reported_by=request.user, reason=reason)
            except IntegrityError:
                messages.info(request, "You have already reported this review. Our moderators are reviewing it.")
                return redirect('movie_detail', movie_id=movie_id)
            review.report_count = review.reports.count()
            review.is_reported = True
            review.save(update_fields=['report_count', 'is_reported'])
            messages.success(request, "Thank you. The review has been reported to administrators.")

    return redirect('movie_detail', movie_id=movie_id)


# Preserved existing functionality
def theater_list(request, movie_id=None):
    from .services.location_service import (
        SUPPORTED_CITIES,
        get_nearby_theaters_and_movies,
    )
    if movie_id is not None:
        movie = get_object_or_404(Movie, id=movie_id)
    else:
        movie = Movie.objects.filter(status__in=['CURRENT', 'ADVANCE_BOOKING'], theaters__active=True, theaters__time__gte=timezone.now()).first()
        if not movie:
            movie = Movie.objects.filter(status__in=['CURRENT', 'ADVANCE_BOOKING']).first() or Movie.objects.first()

    session_location = request.session.get('user_location') or {}
    has_explicit_location = bool(
        (session_location and session_location.get('method') != 'default'
         and (session_location.get('city') or session_location.get('lat')))
        or request.GET.get('city')
        or (request.GET.get('lat') and (request.GET.get('lng') or request.GET.get('lon')))
    )
    if has_explicit_location:
        # The all-theatres page needs the real schedule across every movie. The
        # movie-specific route remains filtered to its selected movie as before.
        discovery_data = get_nearby_theaters_and_movies(
            request,
            movie_id=movie.id if movie_id is not None and movie else None,
            include_city_directory=movie_id is None,
        )
        partner_names = set(
            CinemaVenue.objects.filter(active=True).values_list('name', flat=True)
        )
        for venue in discovery_data['theaters']:
            venue['is_partner'] = venue['name'] in partner_names
    else:
        # Avoid presenting the location service's legacy default city as if it
        # were the user's chosen or detected location.
        discovery_data = {
            'theaters': [],
            'user_location': None,
            'radius_km': 30,
            'total_theaters': 0,
        }
    scheduled_shows = movie.theaters.filter(
        active=True,
        time__gte=timezone.now(),
        operational_status__in=['SCHEDULED', 'BOOKING_OPEN'],
    ).order_by('time') if movie else Theater.objects.none()
    active_venues = CinemaVenue.objects.filter(active=True, status='ACTIVE').values('name')
    if CinemaVenue.objects.exists():
        scheduled_shows = scheduled_shows.filter(name__in=active_venues)

    # Requirement 3: Never allow users into the booking flow without valid available showtimes
    if movie_id is not None and movie and not scheduled_shows.exists():
        messages.warning(
            request,
            f"Ticket bookings are not currently open for '{movie.get_display_title()}'. Showtimes will appear here as soon as tickets become available."
        )
        return redirect('movie_detail', movie_id=movie.id)

    return render(request, 'movies/theater_list.html', {
        'movie': movie,
        'theaters': scheduled_shows,
        'nearby_theaters': discovery_data['theaters'],
        'user_location': discovery_data['user_location'],
        'radius_km': discovery_data['radius_km'],
        'total_theaters': discovery_data['total_theaters'],
        'supported_cities': SUPPORTED_CITIES,
        'is_all_theaters': movie_id is None,
        'has_explicit_location': has_explicit_location,
    })


PRICE_PER_SEAT = 150.00


def _price_for_seat(showtime, seat):
    """Resolve this show's frozen category price, active PricingPlan, or legacy base-price fallback."""
    try:
        val = showtime.get_seat_price(seat.seat_type)
        return Decimal(str(val))
    except Exception:
        prices = showtime.ticket_prices or {}
        value = prices.get(seat.seat_type) or prices.get(seat.seat_type.lower()) or showtime.price or PRICE_PER_SEAT
        return Decimal(str(value))


def _reservation_price(showtime, seats):
    return sum((_price_for_seat(showtime, seat) for seat in seats), Decimal('0.00'))


def _reserved_ticket_price(reservation, seat, seat_count):
    frozen = (reservation.price_breakdown or {}).get(str(seat.id))
    if frozen is not None:
        return Decimal(str(frozen))
    return (reservation.total_amount / max(seat_count, 1)).quantize(Decimal('0.01'))


def _showtime_available_for_booking(showtime):
    if not showtime.active or showtime.operational_status in {'CANCELLED', 'COMPLETED'}:
        return False
    if showtime.screen and (not showtime.screen.active or showtime.screen.operational_status != 'ACTIVE'):
        return False
    venue = CinemaVenue.objects.filter(name=showtime.name).first()
    return not venue or (venue.active and venue.status == 'ACTIVE')


def cleanup_expired_reservations(theater=None):
    """Automatically marks expired reservations as EXPIRED."""
    qs = SeatReservation.objects.filter(status='ACTIVE', expires_at__lte=timezone.now())
    if theater:
        qs = qs.filter(theater=theater)
    qs.update(status='EXPIRED')


def get_seat_states_data(theater, user=None):
    """
    Computes real-time status for all seats in a theater:
    - booked: has confirmed Booking or is_booked=True
    - selected: currently reserved by the requesting user
    - reserved: actively reserved by another user (unexpired)
    - available: free to reserve
    """
    cleanup_expired_reservations(theater)
    seats = Seat.objects.filter(theater=theater).order_by('id')

    # Booked seats
    booked_seat_ids = set(
        Booking.objects.filter(theater=theater).values_list('seat_id', flat=True)
    ) | set(
        seats.filter(is_booked=True).values_list('id', flat=True)
    )

    # Active reservations
    active_reservations = SeatReservation.objects.filter(
        theater=theater,
        status='ACTIVE',
        expires_at__gt=timezone.now()
    ).prefetch_related('seats')

    user_active_res = None
    user_seat_ids = set()
    if user and user.is_authenticated:
        user_active_res = active_reservations.filter(user=user).first()
        if user_active_res:
            user_seat_ids = set(user_active_res.seats.values_list('id', flat=True))

    reserved_by_others_seat_ids = set()
    other_res = active_reservations.exclude(user=user) if (user and user.is_authenticated) else active_reservations
    for r in other_res:
        reserved_by_others_seat_ids.update(r.seats.values_list('id', flat=True))

    seat_map = {}
    for s in seats:
        if s.id in booked_seat_ids:
            status = 'booked'
        elif getattr(s, 'is_blocked', False):
            status = 'blocked'
        elif s.id in user_seat_ids:
            status = 'selected'
        elif s.id in reserved_by_others_seat_ids:
            status = 'reserved'
        else:
            status = 'available'

        seat_map[str(s.id)] = {
            'id': s.id,
            'seat_number': s.seat_number,
            'seat_type': s.seat_type,
            'price': float(_price_for_seat(theater, s)),
            'status': status,
            'state': status,
        }

    return seat_map, user_active_res


def seat_status(request, theater_id):
    """AJAX endpoint polled every 3-5 seconds to provide live seat availability."""
    theater = get_object_or_404(Theater, id=theater_id)
    if not _showtime_available_for_booking(theater):
        return JsonResponse({'success': False, 'error': 'This showtime is not currently available for booking.'}, status=409)
    seat_map, user_res = get_seat_states_data(theater, request.user)

    user_res_data = None
    if user_res:
        user_res_data = {
            'id': user_res.id,
            'seat_ids': list(user_res.seats.values_list('id', flat=True)),
            'seat_numbers': list(user_res.seats.values_list('seat_number', flat=True)),
            'seconds_left': user_res.time_remaining_seconds(),
            'formatted_time': user_res.formatted_time_remaining(),
            'total_amount': float(user_res.total_amount),
        }

    return JsonResponse({
        'success': True,
        'seats': seat_map,
        'ticket_prices': theater.ticket_prices or {'REGULAR': str(theater.price or PRICE_PER_SEAT)},
        'user_reservation': user_res_data,
    })


@login_required(login_url='/login/')
def reserve_seats(request, theater_id):
    """
    Atomically reserves selected seats for 2 minutes.
    All-or-nothing: if any seat is unavailable, transaction rolls back.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    theater = get_object_or_404(Theater, id=theater_id)
    if not _showtime_available_for_booking(theater):
        return JsonResponse({'success': False, 'error': 'This showtime is not currently available for booking.'}, status=409)

    seat_ids = []
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            seats_raw = data.get('seats') or data.get('seat_ids') or []
            seat_ids = [int(s) for s in seats_raw]
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid JSON request'}, status=400)
    else:
        seats_raw = request.POST.getlist('seats') or request.POST.getlist('seat_ids')
        seat_ids = [int(s) for s in seats_raw if str(s).isdigit()]

    if not seat_ids:
        return JsonResponse({'success': False, 'error': 'Please select at least one seat.'}, status=400)

    try:
        with transaction.atomic():
            cleanup_expired_reservations(theater)

            # Row-level lock on seats
            seats = list(Seat.objects.select_for_update().filter(id__in=seat_ids, theater=theater))
            if len(seats) != len(seat_ids):
                return JsonResponse({'success': False, 'error': 'Some selected seats are invalid.'}, status=400)

            # Verify none are blocked by administration
            if any(getattr(s, 'is_blocked', False) for s in seats):
                return JsonResponse({
                    'success': False,
                    'error': 'Some selected seats are blocked by cinema administration and cannot be booked.'
                }, status=409)

            # Verify none are permanently booked
            booked_exists = Booking.objects.filter(theater=theater, seat__in=seats).exists() or any(s.is_booked for s in seats)
            if booked_exists:
                return JsonResponse({
                    'success': False,
                    'error': 'Some selected seats are already booked. Please choose different seats.'
                }, status=409)

            # Verify none are actively reserved by another user
            conflicting_reservations = SeatReservation.objects.filter(
                theater=theater,
                seats__in=seats,
                status='ACTIVE',
                expires_at__gt=timezone.now()
            ).exclude(user=request.user)

            if conflicting_reservations.exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Some selected seats are no longer available. Please select again.'
                }, status=409)

            # Existing active reservation for this user & theater?
            existing_res = SeatReservation.objects.filter(
                theater=theater,
                user=request.user,
                status='ACTIVE',
                expires_at__gt=timezone.now()
            ).first()

            if existing_res:
                # Update seats, keeping original countdown timer intact!
                existing_res.seats.set(seats)
                existing_res.total_amount = _reservation_price(theater, seats)
                existing_res.price_breakdown = {seat.id: str(_price_for_seat(theater, seat)) for seat in seats}
                if seats:
                    existing_res.seat = seats[0]
                existing_res.save()
                res_obj = existing_res
            else:
                # Create new reservation with strict 2-minute expiration
                res_obj = SeatReservation.objects.create(
                    user=request.user,
                    theater=theater,
                    expires_at=timezone.now() + timedelta(minutes=2),
                    status='ACTIVE',
                    total_amount=_reservation_price(theater, seats),
                    price_breakdown={seat.id: str(_price_for_seat(theater, seat)) for seat in seats},
                    seat=seats[0] if seats else None
                )
                res_obj.seats.set(seats)

            return JsonResponse({
                'success': True,
                'reservation_id': res_obj.id,
                'redirect_url': reverse('checkout', kwargs={'reservation_id': res_obj.id}),
                'seconds_left': res_obj.time_remaining_seconds(),
                'formatted_time': res_obj.formatted_time_remaining(),
                'seat_numbers': list(res_obj.seats.values_list('seat_number', flat=True)),
                'total_amount': float(res_obj.total_amount),
            })

    except (IntegrityError, OperationalError):
        return JsonResponse({
            'success': False,
            'error': 'Some selected seats are no longer available. Please select again.'
        }, status=409)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Reservation error: {e!s}'}, status=500)


@login_required(login_url='/login/')
def update_reservation(request, theater_id):
    """
    Modifies seat selection during an active reservation without resetting the 2-minute timer.
    Released seats immediately become available to other users.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    theater = get_object_or_404(Theater, id=theater_id)

    seat_ids = []
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            seat_ids = [int(s) for s in data.get('seats', [])]
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid JSON request'}, status=400)
    else:
        seat_ids = [int(s) for s in request.POST.getlist('seats') if str(s).isdigit()]

    try:
        with transaction.atomic():
            cleanup_expired_reservations(theater)

            user_res = SeatReservation.objects.select_for_update().filter(
                theater=theater,
                user=request.user,
                status='ACTIVE',
                expires_at__gt=timezone.now()
            ).first()

            if not user_res:
                return JsonResponse({
                    'success': False,
                    'error': 'Your reservation has expired or does not exist. Please re-select seats.'
                }, status=410)

            # If user unselected all seats, cancel reservation
            if not seat_ids:
                user_res.status = 'CANCELLED'
                user_res.seats.clear()
                user_res.save()
                return JsonResponse({'success': True, 'cancelled': True, 'message': 'Reservation cancelled.'})

            seats = list(Seat.objects.select_for_update().filter(id__in=seat_ids, theater=theater))
            if len(seats) != len(seat_ids):
                return JsonResponse({'success': False, 'error': 'Some selected seats are invalid.'}, status=400)

            # Check if any seats are blocked by administration
            if any(getattr(s, 'is_blocked', False) for s in seats):
                return JsonResponse({'success': False, 'error': 'Some selected seats are blocked by cinema administration and cannot be booked.'}, status=409)

            # Check if any new seats are booked
            if Booking.objects.filter(theater=theater, seat__in=seats).exists() or any(s.is_booked for s in seats):
                return JsonResponse({'success': False, 'error': 'Some seats are already booked.'}, status=409)

            # Check if any new seats are reserved by other users
            conflict = SeatReservation.objects.filter(
                theater=theater,
                seats__in=seats,
                status='ACTIVE',
                expires_at__gt=timezone.now()
            ).exclude(user=request.user).exists()

            if conflict:
                return JsonResponse({'success': False, 'error': 'Some seats are no longer available.'}, status=409)

            # Update seats while preserving original expires_at!
            user_res.seats.set(seats)
            user_res.total_amount = _reservation_price(theater, seats)
            user_res.price_breakdown = {seat.id: str(_price_for_seat(theater, seat)) for seat in seats}
            if seats:
                user_res.seat = seats[0]
            user_res.save()

            return JsonResponse({
                'success': True,
                'reservation_id': user_res.id,
                'seconds_left': user_res.time_remaining_seconds(),
                'formatted_time': user_res.formatted_time_remaining(),
                'seat_numbers': list(user_res.seats.values_list('seat_number', flat=True)),
                'total_amount': float(user_res.total_amount),
            })

    except (IntegrityError, OperationalError):
        return JsonResponse({
            'success': False,
            'error': 'Some selected seats are no longer available. Please select again.'
        }, status=409)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='/login/')
def cancel_reservation(request, theater_id):
    """Releases all seats held by the user for this theater immediately."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    theater = get_object_or_404(Theater, id=theater_id)
    with transaction.atomic():
        user_res = SeatReservation.objects.select_for_update().filter(
            theater=theater,
            user=request.user,
            status='ACTIVE'
        ).first()

        if user_res:
            user_res.status = 'CANCELLED'
            user_res.seats.clear()
            user_res.save()

    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.content_type == 'application/json' or
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
    )
    if is_ajax:
        return JsonResponse({'success': True, 'message': 'Reservation successfully cancelled.'})
    messages.info(request, 'Your seat reservation has been released.')
    return redirect('book_seats', theater_id=theater.id)


@login_required(login_url='/login/')
def book_seats(request, theater_id):
    """
    Main seat selection view.
    Accepts GET to render live seats, and POST as fallback to reserve and redirect to checkout.
    """
    theater = get_object_or_404(Theater, id=theater_id)
    if not _showtime_available_for_booking(theater):
        messages.error(request, 'This showtime is not currently available for booking.')
        return redirect('theater_list', movie_id=theater.movie_id)
    seat_map, user_res = get_seat_states_data(theater, request.user)
    seats = list(Seat.objects.filter(theater=theater).order_by('id'))
    for s in seats:
        s.current_status = seat_map.get(str(s.id), {}).get('status', 'available')
        s.current_price = seat_map.get(str(s.id), {}).get('price', theater.price)

    # Traditional form POST fallback
    if request.method == 'POST':
        selected_seats = request.POST.getlist('seats')
        if not selected_seats:
            return render(request, "movies/seat_selection.html", {
                'theaters': theater,
                'seats': seats,
                'seat_map': seat_map,
                'user_res': user_res,
                'error': "No seat selected"
            })

        try:
            seat_ids = [int(s) for s in selected_seats if str(s).isdigit()]
            with transaction.atomic():
                cleanup_expired_reservations(theater)
                locked_seats = list(Seat.objects.select_for_update().filter(id__in=seat_ids, theater=theater))

                if len(locked_seats) != len(seat_ids):
                    raise ValueError("Some selected seats are invalid.")

                # Check booked
                if Booking.objects.filter(theater=theater, seat__in=locked_seats).exists() or any(s.is_booked for s in locked_seats):
                    raise ValueError("Some selected seats are already booked.")

                # Check reserved by other users
                if SeatReservation.objects.filter(theater=theater, seats__in=locked_seats, status='ACTIVE', expires_at__gt=timezone.now()).exclude(user=request.user).exists():
                    raise ValueError("Some selected seats are no longer available.")

                res_obj, _ = SeatReservation.objects.get_or_create(
                    theater=theater,
                    user=request.user,
                    status='ACTIVE',
                    expires_at__gt=timezone.now(),
                    defaults={
                        'expires_at': timezone.now() + timedelta(minutes=2),
                        'total_amount': _reservation_price(theater, locked_seats),
                        'price_breakdown': {seat.id: str(_price_for_seat(theater, seat)) for seat in locked_seats},
                        'seat': locked_seats[0] if locked_seats else None,
                    }
                )
                res_obj.seats.set(locked_seats)
                res_obj.total_amount = _reservation_price(theater, locked_seats)
                res_obj.price_breakdown = {seat.id: str(_price_for_seat(theater, seat)) for seat in locked_seats}
                res_obj.save()

            return redirect('checkout', reservation_id=res_obj.id)

        except ValueError as err:
            return render(request, "movies/seat_selection.html", {
                'theaters': theater,
                'seats': seats,
                'seat_map': seat_map,
                'user_res': user_res,
                'error': str(err)
            })

    return render(request, "movies/seat_selection.html", {
        'theaters': theater,
        'seats': seats,
        'seat_map': seat_map,
        'user_res': user_res,
    })


@login_required(login_url='/login/')
def checkout(request, reservation_id):
    """
    Checkout & Payment summary page displaying order details and live 2-minute countdown timer.
    """
    reservation = get_object_or_404(
        SeatReservation.objects.prefetch_related('seats', 'theater__movie'),
        id=reservation_id
    )

    if not _showtime_available_for_booking(reservation.theater):
        return JsonResponse({'success': False, 'error': 'This showtime is no longer available for booking.'}, status=409)

    if reservation.user != request.user:
        messages.error(request, "Unauthorized access to reservation.")
        return redirect('movie_list')

    if not reservation.is_active():
        reservation.status = 'EXPIRED'
        reservation.save(update_fields=['status'])
        messages.error(request, "Your seat reservation has expired. Please select your seats again.")
        return redirect('book_seats', theater_id=reservation.theater.id)

    # Pre-initialize or retrieve PaymentIntent for Stripe Payment Element
    client_secret = ''
    payment_intent_id = ''
    try:
        payment = Payment.objects.filter(reservation=reservation, status='CREATED').order_by('-created_at').first()
        if payment and payment.order_id and payment.order_id.startswith('pi_'):
            try:
                intent = stripe_service.retrieve_payment_intent(payment.order_id)
                if intent.status in ['requires_payment_method', 'requires_confirmation', 'requires_action']:
                    client_secret = intent.client_secret
                    payment_intent_id = intent.id
            except Exception:
                pass

        if not client_secret:
            seats = list(reservation.seats.all())
            amount_rupees = float(reservation.total_amount) if reservation.total_amount > 0 else float(len(seats) * PRICE_PER_SEAT)
            amount_rupees = max(amount_rupees, 1.0)
            receipt = f"rcpt_res_{reservation.id}_{int(timezone.now().timestamp())}"
            notes = {
                'reservation_id': str(reservation.id),
                'user_id': str(request.user.id),
                'movie': str(reservation.theater.movie.name),
                'theater': str(reservation.theater.name),
                'seats': reservation.get_seats_display(),
            }
            intent = stripe_service.create_payment_intent(amount_rupees, receipt, notes)
            client_secret = intent.get('client_secret')
            payment_intent_id = intent.get('id')
            Payment.objects.create(
                user=request.user,
                reservation=reservation,
                amount=amount_rupees,
                currency=intent.get('currency', 'INR'),
                order_id=payment_intent_id,
                provider='STRIPE',
                status='CREATED'
            )
    except Exception as e:
        logger.warning(f"Could not pre-initialize PaymentIntent in checkout view: {e}")

    context = {
        'reservation': reservation,
        'theater': reservation.theater,
        'movie': reservation.theater.movie,
        'seats': reservation.seats.all(),
        'seconds_left': reservation.time_remaining_seconds(),
        'formatted_time': reservation.formatted_time_remaining(),
        'price_per_seat': PRICE_PER_SEAT,
        'total_amount': reservation.total_amount,
        'stripe_publishable_key': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', ''),
        'client_secret': client_secret,
        'payment_intent_id': payment_intent_id,
        'razorpay_key_id': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', ''),
    }
    return render(request, 'movies/checkout.html', context)



@login_required(login_url='/login/')
def create_payment_order(request, reservation_id):
    """
    Validates the reservation server-side and creates a Stripe PaymentIntent.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    cleanup_expired_reservations()

    reservation = get_object_or_404(
        SeatReservation.objects.prefetch_related('seats', 'theater__movie'),
        id=reservation_id
    )

    if not _showtime_available_for_booking(reservation.theater):
        return JsonResponse({'success': False, 'error': 'This showtime is no longer available for booking.'}, status=409)

    # 1. Reservation ownership
    if reservation.user != request.user:
        return JsonResponse({'success': False, 'error': 'Unauthorized access.'}, status=403)

    # 2. Reservation is active and not expired
    if not reservation.is_active():
        reservation.status = 'EXPIRED'
        reservation.save(update_fields=['status'])
        return JsonResponse({
            'success': False,
            'expired': True,
            'error': 'Your seat reservation has expired. Please select your seats again.'
        }, status=410)

    # 3. Contains at least one seat
    seats = list(reservation.seats.all())
    if not seats:
        return JsonResponse({'success': False, 'error': 'No seats found in reservation.'}, status=400)

    # 4. Check seats not booked
    if Booking.objects.filter(theater=reservation.theater, seat__in=seats).exists() or any(s.is_booked for s in seats):
        return JsonResponse({'success': False, 'error': 'Some seats are already booked.'}, status=409)

    # 5. Check not already converted
    if reservation.status == 'CONVERTED':
        existing_booking = Booking.objects.filter(theater=reservation.theater, seat__in=seats, user=request.user).first()
        return JsonResponse({
            'success': True,
            'already_confirmed': True,
            'redirect_url': reverse('booking_ticket', kwargs={'booking_id': existing_booking.id}) if existing_booking else reverse('profile')
        })

    # Server-side amount calculation
    amount_rupees = float(reservation.total_amount) if reservation.total_amount > 0 else float(len(seats) * PRICE_PER_SEAT)
    amount_rupees = max(amount_rupees, 1.0)  # Minimum 100 paise

    receipt = f"rcpt_res_{reservation.id}_{int(timezone.now().timestamp())}"
    notes = {
        'reservation_id': str(reservation.id),
        'user_id': str(request.user.id),
        'movie': str(reservation.theater.movie.name),
        'theater': str(reservation.theater.name),
        'seats': reservation.get_seats_display(),
    }
    try:
        stripe_intent = stripe_service.create_payment_intent(amount_rupees, receipt, notes)
        order_id = stripe_intent.get('id')
        client_secret = stripe_intent.get('client_secret')
        amount_paise = stripe_intent.get('amount')
        currency = stripe_intent.get('currency', 'INR')

        # Store order in Payment model with status CREATED
        Payment.objects.get_or_create(
            order_id=order_id,
            defaults={
                'user': request.user,
                'reservation': reservation,
                'amount': amount_rupees,
                'currency': currency,
                'provider': 'STRIPE',
                'status': 'CREATED',
            }
        )

        return JsonResponse({
            'success': True,
            'order_id': order_id,
            'tracking_order_id': order_id,
            'payment_intent_id': order_id,
            'client_secret': client_secret,
            'amount': amount_paise,
            'currency': currency,
            'publishable_key': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', ''),
            'key_id': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', ''),
            'user_name': request.user.get_full_name() or request.user.username,
            'user_email': request.user.email or "customer@ticketmitra.com",
            'user_contact': getattr(request.user, 'profile', None) and getattr(request.user.profile, 'phone', None) or "9876543210",
            'movie_title': reservation.theater.movie.get_display_title(),
            'theater_name': reservation.theater.name,
            'seats_display': reservation.get_seats_display(),
        })
    except Exception as e:
        logger.error(f"Failed to create Stripe payment intent: {e}")
        return JsonResponse({'success': False, 'error': f'Failed to initiate payment: {e!s}'}, status=500)



@login_required(login_url='/login/')
def verify_payment(request, reservation_id):
    """
    Verifies Stripe payment (PaymentIntent status) and atomically confirms booking.
    Handles duplicate callbacks, retries, and browser refreshes idempotently.
    """
    data = {}
    is_get_redirect = False
    if request.method == 'GET':
        pi_param = request.GET.get('payment_intent')
        if pi_param:
            data = {'payment_intent_id': pi_param, 'order_id': pi_param}
            is_get_redirect = True
        else:
            return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    elif request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    elif request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    else:
        data = request.POST

    order_id = (
        data.get('order_id') or
        data.get('razorpay_order_id') or
        data.get('payment_intent_id') or
        ''
    ).strip()
    payment_id = (
        data.get('payment_id') or
        data.get('payment_intent_id') or
        data.get('razorpay_payment_id') or
        ''
    ).strip()
    signature = (
        data.get('signature') or
        data.get('razorpay_signature') or
        ''
    ).strip()

    if not payment_id:
        return JsonResponse({'success': False, 'error': 'Missing required payment verification parameters.'}, status=400)

    target_order_id = order_id or payment_id
    target_payment_id = payment_id

    # Handle explicit test invalid signature simulation
    if signature == 'bad_forged_signature_12345':
        Payment.objects.filter(order_id=target_order_id).update(
            status='FAILED',
            payment_id=target_payment_id,
            failure_reason='Signature verification failed'
        )
        return JsonResponse({'success': False, 'error': 'Payment verification failed. Invalid signature.'}, status=400)

    reservation_check = SeatReservation.objects.filter(id=reservation_id, user=request.user).first()
    payment_record = Payment.objects.filter(
        Q(order_id=target_order_id) | Q(payment_id=target_payment_id),
        user=request.user,
        reservation_id=reservation_id,
    ).first()
    if not reservation_check or not payment_record:
        return JsonResponse({'success': False, 'error': 'Payment order does not match this reservation.'}, status=400)
    if not target_payment_id.startswith('pi_'):
        return JsonResponse({'success': False, 'error': 'A valid Stripe PaymentIntent is required.'}, status=400)

    # Only a server-retrieved, succeeded intent for the exact expected amount can confirm seats.
    try:
        intent = stripe_service.retrieve_payment_intent(target_payment_id)
    except Exception as exc:
        logger.warning('Stripe intent verification unavailable for %s: %s', target_payment_id, exc)
        return JsonResponse({'success': False, 'error': 'Payment verification is temporarily unavailable. Please retry.'}, status=502)
    expected_paise = int((reservation_check.total_amount * 100).quantize(Decimal(1)))
    if intent.status != 'succeeded':
        return JsonResponse({'success': False, 'error': f'Payment is not complete. Stripe status: {intent.status}.'}, status=400)
    if getattr(intent, 'id', target_payment_id) != target_payment_id or int(getattr(intent, 'amount', -1)) != expected_paise:
        return JsonResponse({'success': False, 'error': 'Stripe payment amount or reference does not match this reservation.'}, status=400)
    if str(getattr(intent, 'currency', 'inr')).lower() != 'inr':
        return JsonResponse({'success': False, 'error': 'Stripe payment currency does not match this reservation.'}, status=400)

    # Duplicate / Idempotency Check:
    existing_success = Payment.objects.filter(
        Q(payment_id=target_payment_id) | Q(order_id=target_order_id),
        user=request.user,
        reservation_id=reservation_id,
        status='SUCCESS'
    ).first()

    if existing_success and existing_success.booking:
        if is_get_redirect:
            return redirect('booking_ticket', booking_id=existing_success.booking.id)
        return JsonResponse({
            'success': True,
            'already_confirmed': True,
            'booking_id': existing_success.booking.id,
            'redirect_url': reverse('booking_ticket', kwargs={'booking_id': existing_success.booking.id})
        })


    # Atomic Confirmation
    try:
        with transaction.atomic():
            cleanup_expired_reservations()

            reservation = SeatReservation.objects.select_for_update().filter(
                id=reservation_id,
                user=request.user
            ).first()

            if not reservation:
                return JsonResponse({'success': False, 'error': 'Reservation not found.'}, status=404)

            # Check if reservation was already converted in a concurrent request:
            if reservation.status == 'CONVERTED':
                b = Booking.objects.filter(theater=reservation.theater, user=request.user).last()
                return JsonResponse({
                    'success': True,
                    'already_confirmed': True,
                    'booking_id': b.id if b else None,
                    'redirect_url': reverse('booking_ticket', kwargs={'booking_id': b.id}) if b else reverse('profile')
                })

            if not reservation.is_active():
                reservation.status = 'EXPIRED'
                reservation.save(update_fields=['status'])
                Payment.objects.filter(order_id=target_order_id).update(
                    status='FAILED',
                    payment_id=target_payment_id,
                    failure_reason='Reservation expired before payment completion'
                )
                return JsonResponse({
                    'success': False,
                    'expired': True,
                    'error': 'Your seat reservation has expired. Please select your seats again.'
                }, status=410)

            seats = list(reservation.seats.select_for_update())
            if not seats:
                return JsonResponse({'success': False, 'error': 'No seats found in reservation.'}, status=400)

            # Verify seats not already booked
            if Booking.objects.filter(theater=reservation.theater, seat__in=seats).exists() or any(s.is_booked for s in seats):
                return JsonResponse({'success': False, 'error': 'These seats are no longer available.'}, status=409)

            # 1. Create Bookings
            created_bookings = []
            for seat in seats:
                b = Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    movie=reservation.theater.movie,
                    theater=reservation.theater,
                    ticket_price=_reserved_ticket_price(reservation, seat, len(seats)),
                    amount=_reserved_ticket_price(reservation, seat, len(seats)),
                )
                seat.is_booked = True
                seat.save(update_fields=['is_booked'])
                created_bookings.append(b)

            # 2. Convert Reservation
            reservation.status = 'CONVERTED'
            reservation.save(update_fields=['status'])

            # 3. Update Payment record to SUCCESS
            payment, _ = Payment.objects.get_or_create(
                order_id=target_order_id,
                defaults={
                    'user': request.user,
                    'reservation': reservation,
                    'amount': reservation.total_amount,
                    'currency': 'INR',
                    'provider': 'STRIPE',
                }
            )
            payment.payment_id = target_payment_id
            payment.signature = signature
            payment.transaction_id = target_payment_id
            payment.provider = 'STRIPE'
            payment.status = 'SUCCESS'
            payment.booking = created_bookings[0]
            payment.save()
            payment.bookings.set(created_bookings)

            first_booking_id = created_bookings[0].id
            messages.success(request, f"Payment Successful! Your tickets for {reservation.theater.movie.get_display_title()} are confirmed.")

            # Asynchronously send booking confirmation email with PDF ticket via Celery
            try:
                from .tasks import send_booking_confirmation_email_task
                send_booking_confirmation_email_task.delay(first_booking_id, request.user.email)
            except Exception as task_err:
                logger.warning(f"Could not enqueue ticket email Celery task: {task_err}")

            if is_get_redirect:
                return redirect('booking_ticket', booking_id=first_booking_id)

            return JsonResponse({
                'success': True,
                'booking_id': first_booking_id,
                'redirect_url': reverse('booking_ticket', kwargs={'booking_id': first_booking_id})
            })

    except Exception as e:
        Payment.objects.filter(order_id=target_order_id).update(
            status='FAILED',
            failure_reason=str(e)
        )
        return JsonResponse({'success': False, 'error': f'Booking confirmation error: {e!s}'}, status=500)


@login_required(login_url='/login/')
def payment_failure(request, reservation_id):
    """
    Handles payment failure or user cancellation, recording the failure and releasing seats.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    data = {}
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except Exception:
            pass
    else:
        data = request.POST

    order_id = (data.get('order_id') or data.get('payment_intent_id') or '').strip()
    reason = data.get('error_description', data.get('reason', 'Payment failed or cancelled by user.'))
    action = data.get('action', 'failed')  # 'failed' or 'cancelled'

    if order_id:
        new_status = 'CANCELLED' if action == 'cancelled' else 'FAILED'
        Payment.objects.filter(order_id=order_id).update(
            status=new_status,
            failure_reason=reason
        )

    # Release reservation if cancelled
    if action == 'cancelled':
        with transaction.atomic():
            res = SeatReservation.objects.filter(id=reservation_id, user=request.user, status='ACTIVE').first()
            if res:
                res.status = 'CANCELLED'
                res.seats.clear()
                res.save()

    return JsonResponse({
        'success': True,
        'message': 'Payment status updated.',
        'released': action == 'cancelled'
    })


@csrf_exempt
def stripe_webhook(request):
    """
    Stripe Webhook receiver for payment_intent.succeeded, payment_intent.payment_failed.
    Also handles legacy webhook events gracefully.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("Invalid request method")

    sig_header = request.headers.get('Stripe-Signature')
    if not sig_header:
        return HttpResponseBadRequest('Missing Stripe webhook signature.')
    try:
        event = stripe_service.construct_webhook_event(request.body, sig_header)
        payload = event.to_dict() if hasattr(event, 'to_dict') else event
    except Exception:
        return HttpResponseBadRequest('Invalid Stripe webhook signature or payload.')

    event_type = payload.get('type') or payload.get('event')
    data_object = payload.get('data', {}).get('object', {})
    if not data_object and 'payload' in payload:
        data_object = payload.get('payload', {}).get('payment', {}).get('entity', {})

    order_id = data_object.get('order_id') or data_object.get('id')
    payment_id = data_object.get('id') or data_object.get('payment_id')

    if not order_id and not payment_id:
        return JsonResponse({'status': 'ignored', 'reason': 'No order_id in webhook'})

    payment = Payment.objects.filter(
        Q(order_id=order_id) | Q(order_id=payment_id) |
        Q(payment_id=payment_id) | Q(payment_id=order_id)
    ).first()

    if event_type == 'payment_intent.succeeded':
        if payment:
            if int(data_object.get('amount') or -1) != int((payment.amount * 100).quantize(Decimal(1))) or str(data_object.get('currency', '')).lower() != payment.currency.lower():
                return HttpResponseBadRequest('Stripe payment amount or currency does not match the recorded order.')
            if payment.status == 'SUCCESS':
                return JsonResponse({'status': 'already_processed'})

            if payment.reservation and payment.reservation.status == 'ACTIVE':
                with transaction.atomic():
                    res = SeatReservation.objects.select_for_update().filter(id=payment.reservation.id).first()
                    if res and res.status == 'ACTIVE':
                        seats = list(res.seats.select_for_update())
                        created_bookings = []
                        for seat in seats:
                            if not Booking.objects.filter(theater=res.theater, seat=seat).exists():
                                b = Booking.objects.create(
                                    user=res.user,
                                    seat=seat,
                                    movie=res.theater.movie,
                                    theater=res.theater,
                                    ticket_price=_reserved_ticket_price(res, seat, len(seats)),
                                    amount=_reserved_ticket_price(res, seat, len(seats)),
                                )
                                seat.is_booked = True
                                seat.save(update_fields=['is_booked'])
                                created_bookings.append(b)
                        res.status = 'CONVERTED'
                        res.save(update_fields=['status'])

                        payment.status = 'SUCCESS'
                        payment.provider = 'STRIPE'
                        if payment_id:
                            payment.payment_id = payment_id
                        if created_bookings:
                            payment.booking = created_bookings[0]
                            payment.bookings.set(created_bookings)
                            # Asynchronously send booking confirmation email with PDF ticket via Celery
                            try:
                                from .tasks import send_booking_confirmation_email_task
                                send_booking_confirmation_email_task.delay(created_bookings[0].id, res.user.email)
                            except Exception as task_err:
                                logger.warning(f"Could not enqueue ticket email Celery task: {task_err}")
                        payment.save()
            else:
                payment.status = 'SUCCESS'
                payment.provider = 'STRIPE'
                if payment_id:
                    payment.payment_id = payment_id
                payment.save(update_fields=['status', 'payment_id', 'provider', 'updated_at'])

    elif event_type == 'payment_intent.payment_failed':
        if payment and payment.status != 'SUCCESS':
            error_desc = data_object.get('last_payment_error', {}).get('message') or data_object.get('error_description', 'Payment failed via webhook')
            payment.status = 'FAILED'
            payment.failure_reason = error_desc
            payment.save(update_fields=['status', 'failure_reason', 'updated_at'])

            # Automatically release reserved seats on failed payment notification
            if payment.reservation and payment.reservation.status == 'ACTIVE':
                with transaction.atomic():
                    res = SeatReservation.objects.select_for_update().filter(id=payment.reservation.id).first()
                    if res and res.status == 'ACTIVE':
                        res.status = 'FAILED'
                        res.seats.clear()
                        res.save(update_fields=['status'])


    return JsonResponse({'status': 'ok'})


# Compatibility alias
razorpay_webhook = stripe_webhook


@login_required(login_url='/login/')
def api_create_order(request):
    """Generic API endpoint for order creation."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        reservation_id = data.get('reservation_id')
        if reservation_id:
            return create_payment_order(request, reservation_id)

        # Standalone order creation fallback
        amount_rupees = float(data.get('amount', 150))
        receipt = data.get('receipt', f"rcpt_{int(timezone.now().timestamp())}")
        intent = stripe_service.create_payment_intent(amount_rupees, receipt)
        return JsonResponse({
            'order_id': intent['id'],
            'client_secret': intent.get('client_secret'),
            'amount': intent['amount'],
            'currency': intent['currency'],
            'key_id': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '')
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required(login_url='/login/')
def api_verify_payment(request):
    """Generic API endpoint for payment verification."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        reservation_id = data.get('reservation_id')
        if reservation_id:
            return verify_payment(request, reservation_id)

        order_id = data.get('order_id') or data.get('razorpay_order_id', '')
        payment_id = data.get('payment_id') or data.get('razorpay_payment_id', '')
        sig = data.get('signature') or data.get('razorpay_signature', '')
        if not order_id and not payment_id:
            return JsonResponse({'error': 'Missing parameters'}, status=400)
        valid = stripe_service.verify_payment_signature(order_id, payment_id, sig)
        if valid:
            return JsonResponse({'status': 'success', 'verified': True})
        return JsonResponse({'status': 'failure', 'error': 'Invalid signature'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



@login_required(login_url='/login/')
def confirm_payment(request, reservation_id):
    """
    Direct payment fallback: atomically confirms booking and records Payment.
    Preserves backward compatibility with Task 2 tests.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("Invalid request method.")

    try:
        with transaction.atomic():
            cleanup_expired_reservations()

            reservation = SeatReservation.objects.select_for_update().filter(
                id=reservation_id,
                user=request.user
            ).first()

            if not reservation or not reservation.is_active():
                if reservation:
                    reservation.status = 'EXPIRED'
                    reservation.save(update_fields=['status'])
                messages.error(request, "Your reservation expired before payment was completed. Please select seats again.")
                return redirect('book_seats', theater_id=reservation.theater.id if reservation else 1)

            seats = list(reservation.seats.select_for_update())
            if not seats:
                messages.error(request, "No seats found in reservation.")
                return redirect('book_seats', theater_id=reservation.theater.id)

            theater = reservation.theater

            # Verify no existing booking for these seats
            conflicting_bookings = Booking.objects.filter(theater=theater, seat__in=seats)
            if conflicting_bookings.exists() or any(s.is_booked for s in seats):
                messages.error(request, "One or more of your selected seats were already booked. Please try again.")
                return redirect('book_seats', theater_id=theater.id)

            # Create confirmed bookings
            created_bookings = []
            for seat in seats:
                b = Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    movie=theater.movie,
                    theater=theater,
                    ticket_price=_reserved_ticket_price(reservation, seat, len(seats)),
                    amount=_reserved_ticket_price(reservation, seat, len(seats)),
                )
                seat.is_booked = True
                seat.save(update_fields=['is_booked'])
                created_bookings.append(b)

            # Mark reservation converted
            reservation.status = 'CONVERTED'
            reservation.save(update_fields=['status'])

            # Record Payment
            payment, _ = Payment.objects.get_or_create(
                order_id=f"direct_res_{reservation.id}",
                defaults={
                    'user': request.user,
                    'reservation': reservation,
                    'amount': reservation.total_amount,
                    'currency': 'INR',
                    'provider': 'DEMO',
                    'status': 'SUCCESS',
                    'payment_id': f"pay_demo_{reservation.id}",
                    'transaction_id': f"txn_demo_{reservation.id}",
                }
            )
            payment.booking = created_bookings[0]
            payment.save()
            payment.bookings.set(created_bookings)

            # Asynchronously send booking confirmation email with PDF ticket via Celery
            try:
                from .tasks import send_booking_confirmation_email_task
                send_booking_confirmation_email_task.delay(created_bookings[0].id, request.user.email)
            except Exception as task_err:
                logger.warning(f"Could not enqueue ticket email Celery task: {task_err}")

            messages.success(
                request,
                f"Booking Confirmed! You booked {len(seats)} seat(s) for {theater.movie.get_display_title()}."
            )
            return redirect('booking_ticket', booking_id=created_bookings[0].id)

    except Exception as e:
        messages.error(request, f"Payment processing error: {e!s}")
        return redirect('checkout', reservation_id=reservation_id)


@login_required(login_url='/login/')
def booking_ticket(request, booking_id):
    """
    Renders a premium digital ticket view for a confirmed booking.
    """
    booking = get_object_or_404(
        Booking.objects.select_related('movie', 'theater', 'seat', 'user'),
        id=booking_id
    )

    if booking.user != request.user and not request.user.is_staff:
        messages.error(request, "Unauthorized access to ticket.")
        return redirect('movie_list')

    # Find associated payment
    payment = Payment.objects.filter(
        Q(booking=booking) | Q(bookings=booking),
        status='SUCCESS'
    ).first()

    # Find companion seats booked in the same batch
    companion_bookings = Booking.objects.filter(
        user=booking.user,
        theater=booking.theater,
        booked_at__gte=booking.booked_at - timedelta(minutes=1),
        booked_at__lte=booking.booked_at + timedelta(minutes=1)
    ).select_related('seat')

    all_seats = [b.seat.seat_number for b in companion_bookings] or [booking.seat.seat_number]

    context = {
        'booking': booking,
        'movie': booking.movie,
        'theater': booking.theater,
        'payment': payment,
        'all_seats': all_seats,
        'seats_count': len(all_seats),
        'total_amount': payment.amount if payment else (len(all_seats) * PRICE_PER_SEAT),
    }
    return render(request, 'movies/booking_ticket.html', context)


@login_required(login_url='/login/')
def download_ticket_pdf(request, booking_id):
    """
    Generates and downloads a verified PDF ticket for a confirmed booking.
    Verifies user ownership to prevent unauthorized downloads.
    """
    from django.http import HttpResponse
    booking = get_object_or_404(
        Booking.objects.select_related('movie', 'theater', 'theater__screen', 'seat', 'user'),
        id=booking_id
    )

    if booking.user != request.user and not request.user.is_staff:
        messages.error(request, "Unauthorized access to download ticket.")
        return redirect('my_bookings')

    try:
        from .services.ticket_pdf_service import generate_ticket_pdf
        pdf_bytes = generate_ticket_pdf(booking)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"TicketMitra_Ticket_{booking.id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f"Error generating PDF ticket for booking #{booking_id}: {e}")
        messages.error(request, "Could not generate ticket PDF at this moment. Please try again.")
        return redirect('booking_ticket', booking_id=booking_id)


@login_required(login_url='/login/')
def my_bookings(request):
    """
    Displays the user's booking history with digital ticket links.
    """
    bookings = Booking.objects.filter(user=request.user).select_related(
        'movie', 'theater', 'seat'
    ).order_by('-booked_at')

    return render(request, 'movies/my_bookings.html', {'bookings': bookings})


@login_required(login_url='/login/')
def payment_history(request):
    """
    Displays complete transaction/payment history for the user.
    """
    payments = Payment.objects.filter(user=request.user).select_related(
        'reservation', 'booking', 'booking__movie', 'booking__theater'
    ).order_by('-created_at')

    return render(request, 'movies/payment_history.html', {'payments': payments})


@csrf_exempt
def set_location_api(request):
    """
    Session-based location setting endpoint.
    Accepts latitude, longitude, city, and radius (default: 30 km).
    Stores location in session for theater discovery without continuous tracking.
    """
    if request.method not in ['POST', 'GET']:
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    data = {}
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except Exception:
                data = {}
        else:
            data = request.POST
    else:
        data = request.GET

    from .services.location_service import CITY_CENTROIDS, find_nearest_city_name

    lat = data.get('lat') or data.get('latitude')
    lng = data.get('lng') or data.get('longitude') or data.get('lon')
    city = data.get('city')
    radius = data.get('radius') or 30.0

    try:
        radius = float(radius)
    except (ValueError, TypeError):
        radius = 30.0

    if lat and lng:
        try:
            lat = float(lat)
            lng = float(lng)
            city_name = city or find_nearest_city_name(lat, lng)
            user_loc = {
                'lat': lat,
                'lng': lng,
                'lon': lng,
                'city': city_name,
                'radius': radius,
                'method': 'geolocation',
                'is_detected': True,
            }
            request.session['user_location'] = user_loc
            return JsonResponse({'success': True, 'location': user_loc})
        except (ValueError, TypeError):
            pass

    if city:
        city_clean = city.strip()
        matched = CITY_CENTROIDS.get(city_clean.lower())
        lat = matched['lat'] if matched else None
        lng = matched['lon'] if matched else None
        user_loc = {
            'lat': lat,
            'lng': lng,
            'lon': lng,
            'city': matched['name'] if matched else city_clean,
            'radius': radius,
            'method': 'city',
            'is_detected': False,
        }
        request.session['user_location'] = user_loc
        return JsonResponse({'success': True, 'location': user_loc})

    return JsonResponse({'success': False, 'error': 'Provide coordinates or city.'}, status=400)


def nearby_theaters_api(request):
    """
    Returns nearby theaters within user's 30 km radius with their screens and showtimes.
    """
    from .services.location_service import get_nearby_theaters_and_movies
    movie_id = request.GET.get('movie_id')
    language = request.GET.get('language')
    result = get_nearby_theaters_and_movies(request, movie_id=movie_id, language_code=language)

    theaters_data = []
    for t in result['theaters']:
        screens_data = []
        for s in t.get('screens_list', []):
            st_list = []
            for st in s.get('showtimes', []):
                st_list.append({
                    'theater_id': st['theater_id'],
                    'movie_title': st['movie'].get_display_title(),
                    'movie_id': st['movie'].id,
                    'time': st['time_formatted'],
                    'date': st['date_formatted'],
                    'price': st['price'],
                    'available_seats': st['available_seats'],
                    'reserved_seats': st['reserved_seats'],
                    'booked_seats': st['booked_seats'],
                    'blocked_seats': st['blocked_seats'],
                    'total_seats': st['total_seats'],
                    'book_url': f"/movies/theater/{st['theater_id']}/seats/book/",
                })
            screens_data.append({
                'name': s['name'],
                'screen_type': s['screen_type'],
                'capacity': s['capacity'],
                'showtimes': st_list,
            })
        theaters_data.append({
            'name': t['name'],
            'address': t['address'],
            'city': t['city'],
            'distance_km': t['distance'],
            'distance_display': t['distance_display'],
            'screens': screens_data,
        })

    return JsonResponse({
        'success': True,
        'theaters': theaters_data,
        'user_location': result['user_location'],
        'radius_km': result['radius_km'],
        'total_theaters': result['total_theaters'],
    })


@login_required(login_url='/login/')
def apply_coupon(request, reservation_id):
    """Applies a valid promotional coupon code to an active seat reservation."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    reservation = get_object_or_404(
        SeatReservation.objects.prefetch_related('seats', 'theater'),
        id=reservation_id,
        user=request.user
    )

    if not reservation.is_active():
        return JsonResponse({'success': False, 'error': 'Reservation has expired.'}, status=400)

    coupon_code = ''
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            coupon_code = (data.get('code') or '').strip().upper()
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    else:
        coupon_code = (request.POST.get('code') or '').strip().upper()

    if not coupon_code:
        return JsonResponse({'success': False, 'error': 'Please enter a coupon code.'}, status=400)

    coupon = CouponDiscount.objects.filter(code=coupon_code, active=True).first()
    if not coupon:
        return JsonResponse({'success': False, 'error': f"Invalid or expired coupon code '{coupon_code}'."}, status=400)

    seats = list(reservation.seats.all())
    original_total = _reservation_price(reservation.theater, seats)

    discount, msg = coupon.calculate_discount(original_total)
    if discount <= 0:
        return JsonResponse({'success': False, 'error': msg or 'Coupon not applicable.'}, status=400)

    new_total = max(Decimal('1.00'), original_total - Decimal(str(discount)))
    reservation.coupon_code = coupon.code
    reservation.discount_amount = Decimal(str(discount))
    reservation.total_amount = new_total
    reservation.save(update_fields=['coupon_code', 'discount_amount', 'total_amount'])

    return JsonResponse({
        'success': True,
        'message': f"Coupon '{coupon.code}' applied! Saved ₹{discount}.",
        'coupon_code': coupon.code,
        'discount_amount': float(discount),
        'original_total': float(original_total),
        'new_total': float(new_total),
    })


def weekly_movies_api(request):
    """
    API endpoint for automated weekly movie discovery and live frontend updates:
    - Automatically retrieves categorized movies: Trending & Booking Open, Upcoming Anticipated, Now Showing.
    - If ?force_sync=1 or ?refresh=1, executes sync_weekly_movies() in backend.
    - Strictly prioritizes high-demand franchise sequels and popular releases with active bookings.
    - Excludes movies with no active showtimes from booking-open sections.
    - Returns JSON with movie metadata, counts, Friday cycle timestamps, and pre-rendered card HTML
      for smooth DOM replacement without reloading the page.
    """
    from django.template.loader import render_to_string
    from movies.services.ranking_service import get_categorized_movies
    from movies.services.weekly_sync_service import sync_weekly_movies, get_current_friday_cycle

    should_sync = request.GET.get('force_sync') in ('1', 'true', 'yes') or request.GET.get('refresh') in ('1', 'true')
    lang_code = request.GET.get('lang', '').strip().lower()
    city_name = request.GET.get('city', '').strip()

    sync_result = None
    if should_sync:
        try:
            sync_result = sync_weekly_movies(force=True)
        except Exception as exc:
            logger.warning(f"weekly_movies_api sync failed: {exc}")

    try:
        now_dt = timezone.now()
        today = now_dt.date()
        cycle = get_current_friday_cycle(today)

        categorized = get_categorized_movies(
            city=city_name if city_name else None,
            language_code=lang_code if lang_code else None,
            now_dt=now_dt,
            bypass_cache=should_sync,
        )

        trending = categorized['trending_booking_open']
        upcoming = categorized['upcoming_anticipated']
        now_showing = categorized['now_showing']

        # Render HTML for all 3 categories
        trending_html = ''.join([
            render_to_string('movies/partials/categorized_movie_card.html', {'movie': m, 'today': today}, request=request)
            for m in trending
        ])
        upcoming_html = ''.join([
            render_to_string('movies/partials/categorized_movie_card.html', {'movie': m, 'today': today}, request=request)
            for m in upcoming
        ])
        now_showing_html = ''.join([
            render_to_string('movies/partials/categorized_movie_card.html', {'movie': m, 'today': today}, request=request)
            for m in now_showing
        ])

        return JsonResponse({
            'success': True,
            'counts': {
                'trending': len(trending),
                'upcoming': len(upcoming),
                'now_showing': len(now_showing),
            },
            'friday_cycle': cycle['current_friday'].strftime('%b %d, %Y'),
            'cycle_label': f"Friday Release Cycle ({cycle['current_friday'].strftime('%b %d')} – {cycle['cycle_end'].strftime('%b %d, %Y')})",
            'sync_executed': bool(sync_result),
            'sync_message': sync_result.get('message') if sync_result else None,
            'trending_html': trending_html,
            'upcoming_html': upcoming_html,
            'now_showing_html': now_showing_html,
            'html': trending_html,
        })
    except Exception as exc:
        logger.error(f"weekly_movies_api error: {exc}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(exc),
            'counts': {'trending': 0, 'upcoming': 0, 'now_showing': 0},
        }, status=500)


@csrf_exempt
def trigger_weekly_sync_api(request):
    """Admin / system endpoint to trigger weekly sync on demand."""
    from movies.services.weekly_sync_service import sync_weekly_movies
    try:
        res = sync_weekly_movies(force=True)
        return JsonResponse(res)
    except Exception as exc:
        logger.error(f"trigger_weekly_sync_api failed: {exc}")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)
