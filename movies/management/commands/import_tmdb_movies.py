from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from movies.models import CastMember, Genre, Language, Movie, MoviePoster
from movies.services.tmdb_service import TMDBService

LANGUAGE_MAP = {
    'en': 'English',
    'kn': 'Kannada',
    'ta': 'Tamil',
    'te': 'Telugu',
    'hi': 'Hindi',
    'ml': 'Malayalam',
    'es': 'Spanish',
    'fr': 'French',
    'ja': 'Japanese',
    'ko': 'Korean',
    'de': 'German',
    'it': 'Italian',
    'zh': 'Chinese',
    'bn': 'Bengali',
    'mr': 'Marathi',
    'pa': 'Punjabi',
}


class Command(BaseCommand):
    help = "Fetch and synchronize movies from TMDB API into the local database."

    def add_arguments(self, parser):
        parser.add_argument('--popular', action='store_true', help='Import popular movies')
        parser.add_argument('--trending', action='store_true', help='Import trending movies')
        parser.add_argument('--now-playing', action='store_true', help='Import now playing movies')
        parser.add_argument('--upcoming', action='store_true', help='Import upcoming movies')
        parser.add_argument('--top-rated', action='store_true', help='Import top rated movies')
        parser.add_argument('--pages', type=int, default=1, help='Number of pages to fetch (default: 1)')
        parser.add_argument('--search', type=str, default=None, help='Search and import specific movie keyword')

    def handle(self, *args, **options):
        tmdb = TMDBService()
        if not tmdb.api_key:
            self.stderr.write(self.style.ERROR(
                "Error: TMDB_API_KEY is not configured in settings or .env file.\n"
                "Please set TMDB_API_KEY to fetch movies."
            ))
            return

        pages = options.get('pages', 1)
        search_query = options.get('search')
        is_popular = options.get('popular')
        is_trending = options.get('trending')
        is_now_playing = options.get('now_playing')
        is_upcoming = options.get('upcoming')
        is_top_rated = options.get('top_rated')

        # If no specific category flag provided, default to popular
        if not any([search_query, is_popular, is_trending, is_now_playing, is_upcoming, is_top_rated]):
            is_popular = True

        movie_items = []

        self.stdout.write(self.style.NOTICE("Starting TMDB synchronization..."))

        for page in range(1, pages + 1):
            if search_query:
                self.stdout.write(f"Searching movies for '{search_query}' (Page {page})...")
                res = tmdb.search_movies(search_query, page=page)
            elif is_trending:
                self.stdout.write(f"Fetching Trending movies (Page {page})...")
                res = tmdb.get_trending_movies(page=page)
            elif is_now_playing:
                self.stdout.write(f"Fetching Now Playing movies (Page {page})...")
                res = tmdb.get_now_playing_movies(page=page)
            elif is_upcoming:
                self.stdout.write(f"Fetching Upcoming movies (Page {page})...")
                res = tmdb.get_upcoming_movies(page=page)
            elif is_top_rated:
                self.stdout.write(f"Fetching Top Rated movies (Page {page})...")
                res = tmdb.get_top_rated_movies(page=page)
            else:
                self.stdout.write(f"Fetching Popular movies (Page {page})...")
                res = tmdb.get_popular_movies(page=page)

            results = res.get('results', [])
            if not results:
                self.stdout.write(self.style.WARNING(f"No results found for page {page}."))
                break
            movie_items.extend(results)

        # Deduplicate results by TMDB ID
        unique_movies = {item['id']: item for item in movie_items if item.get('id')}
        self.stdout.write(self.style.SUCCESS(f"Found {len(unique_movies)} distinct movies to process."))

        created_count = 0
        updated_count = 0

        for tmdb_id, basic_data in unique_movies.items():
            try:
                # Fetch full detailed data for this movie (including credits, videos, release_dates, images)
                detail = tmdb.get_movie_details(tmdb_id, append_to_response='videos,credits,release_dates,images')
                if not detail or not detail.get('id'):
                    # Fallback to basic data if details fail
                    detail = basic_data

                title = detail.get('title') or detail.get('name') or basic_data.get('title') or 'Untitled Movie'
                original_title = detail.get('original_title') or basic_data.get('original_title') or ''
                overview = detail.get('overview') or basic_data.get('overview') or ''
                release_date_str = detail.get('release_date') or basic_data.get('release_date')
                release_date = parse_date(release_date_str) if release_date_str else None
                runtime = detail.get('runtime') or None
                popularity = float(detail.get('popularity') or basic_data.get('popularity') or 0.0)
                vote_average = round(float(detail.get('vote_average') or basic_data.get('vote_average') or 0.0), 1)
                vote_count = int(detail.get('vote_count') or basic_data.get('vote_count') or 0)

                poster_path = detail.get('poster_path') or basic_data.get('poster_path')
                poster_url = tmdb.get_poster_url(poster_path) if poster_path else ''

                backdrop_path = detail.get('backdrop_path') or basic_data.get('backdrop_path')
                backdrop_url = tmdb.get_backdrop_url(backdrop_path) if backdrop_path else ''

                trailer_url = tmdb.extract_youtube_trailer_url(detail.get('videos')) or ''
                age_certification = tmdb.extract_age_certification(detail.get('release_dates')) or ''

                # Upsert Movie by tmdb_id
                movie, created = Movie.objects.get_or_create(
                    tmdb_id=tmdb_id,
                    defaults={
                        'name': title,
                        'title': title,
                        'original_title': original_title,
                        'description': overview,
                        'release_date': release_date,
                        'runtime': runtime,
                        'popularity': popularity,
                        'tmdb_rating': vote_average,
                        'rating': vote_average,
                        'vote_count': vote_count,
                        'poster_url': poster_url,
                        'backdrop_url': backdrop_url,
                        'trailer_url': trailer_url,
                        'age_certification': age_certification,
                    }
                )

                if not created:
                    # Update fields
                    movie.title = title
                    movie.name = title
                    movie.original_title = original_title
                    movie.description = overview
                    if release_date:
                        movie.release_date = release_date
                    if runtime:
                        movie.runtime = runtime
                    movie.popularity = popularity
                    movie.tmdb_rating = vote_average
                    movie.rating = vote_average
                    movie.vote_count = vote_count
                    if poster_url:
                        movie.poster_url = poster_url
                    if backdrop_url:
                        movie.backdrop_url = backdrop_url
                    if trailer_url:
                        movie.trailer_url = trailer_url
                    if age_certification:
                        movie.age_certification = age_certification
                    movie.save()
                    updated_count += 1
                else:
                    created_count += 1

                # Sync Genres
                genres_data = detail.get('genres', [])
                genre_objs = []
                for g in genres_data:
                    g_id = g.get('id')
                    g_name = g.get('name', '').strip()
                    if g_name:
                        genre_obj, _ = Genre.objects.get_or_create(name=g_name, defaults={'tmdb_id': g_id})
                        if g_id and not genre_obj.tmdb_id:
                            genre_obj.tmdb_id = g_id
                            genre_obj.save()
                        genre_objs.append(genre_obj)
                if genre_objs:
                    movie.genres.set(genre_objs)

                # Sync Languages
                orig_lang_code = (detail.get('original_language') or basic_data.get('original_language') or '').lower()
                lang_objs = []
                if orig_lang_code:
                    lang_name = LANGUAGE_MAP.get(orig_lang_code, orig_lang_code.upper())
                    lang_obj, _ = Language.objects.get_or_create(code=orig_lang_code, defaults={'name': lang_name})
                    lang_objs.append(lang_obj)

                for spoken in detail.get('spoken_languages', []):
                    s_code = (spoken.get('iso_639_1') or '').lower()
                    s_name = spoken.get('english_name') or spoken.get('name') or LANGUAGE_MAP.get(s_code, s_code.upper())
                    if s_code:
                        l_obj, _ = Language.objects.get_or_create(code=s_code, defaults={'name': s_name})
                        if l_obj not in lang_objs:
                            lang_objs.append(l_obj)
                if lang_objs:
                    movie.languages.set(lang_objs)

                # Sync Cast Members (top 8)
                credits_data = detail.get('credits', {})
                cast_list = credits_data.get('cast', [])[:8]
                cast_objs = []
                cast_names = []
                for actor in cast_list:
                    a_name = actor.get('name', '').strip()
                    if not a_name:
                        continue
                    cast_names.append(a_name)
                    a_id = actor.get('id')
                    character = actor.get('character', '').strip()
                    profile_path = actor.get('profile_path')
                    profile_url = tmdb.get_profile_url(profile_path) if profile_path else ''

                    cast_obj, _ = CastMember.objects.get_or_create(
                        name=a_name,
                        character=character,
                        defaults={
                            'tmdb_id': a_id,
                            'profile_path': profile_path or '',
                            'profile_image_url': profile_url,
                        }
                    )
                    cast_objs.append(cast_obj)

                if cast_objs:
                    movie.cast_members.set(cast_objs)

                # Maintain legacy cast text field
                if cast_names:
                    movie.cast = ", ".join(cast_names)
                    movie.save(update_fields=['cast'])

                # Sync Posters (up to 6)
                images_data = detail.get('images', {})
                posters_list = images_data.get('posters', [])[:6]
                if posters_list:
                    for idx, p in enumerate(posters_list):
                        p_path = p.get('file_path')
                        if p_path:
                            p_url = tmdb.get_poster_url(p_path)
                            MoviePoster.objects.get_or_create(
                                movie=movie,
                                image_url=p_url,
                                defaults={'is_primary': (idx == 0 and not movie.image)}
                            )

                status = "Created" if created else "Updated"
                self.stdout.write(f"[{status}] {movie.get_display_title()} (TMDB #{tmdb_id})")

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error processing TMDB ID {tmdb_id}: {e!s}"))

        self.stdout.write(self.style.SUCCESS(
            f"Successfully processed movies! Created: {created_count}, Updated: {updated_count}."
        ))
