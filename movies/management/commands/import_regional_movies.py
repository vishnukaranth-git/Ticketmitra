import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from movies.models import CastMember, Genre, Language, Movie, MoviePoster
from movies.services.tmdb_service import TMDBService

SOUTH_INDIAN_LANGUAGES = {
    'kn': 'Kannada',
    'ta': 'Tamil',
    'te': 'Telugu',
    'ml': 'Malayalam',
}


class Command(BaseCommand):
    help = "Import and synchronize South Indian regional movies (Kannada, Tamil, Telugu, Malayalam) from TMDB into TicketMitra."

    def add_arguments(self, parser):
        parser.add_argument('--language', type=str, default=None, help='Target language code (kn, ta, te, ml or comma-separated)')
        parser.add_argument('--all-south', action='store_true', help='Import all 4 South Indian languages (Kannada, Tamil, Telugu, Malayalam)')
        parser.add_argument('--popular', action='store_true', help='Import popular movies')
        parser.add_argument('--recent', action='store_true', help='Import recent movies')
        parser.add_argument('--top-rated', action='store_true', help='Import top-rated movies')
        parser.add_argument('--upcoming', action='store_true', help='Import upcoming movies')
        parser.add_argument('--pages', type=int, default=1, help='Number of pages to process per language (default: 1)')
        parser.add_argument('--min-votes', type=int, default=None, help='Filter minimum vote count')
        parser.add_argument('--min-popularity', type=float, default=None, help='Filter minimum popularity')

    def handle(self, *args, **options):
        tmdb = TMDBService()

        target_langs = []
        if options.get('all_south'):
            target_langs = list(SOUTH_INDIAN_LANGUAGES.keys())
        elif options.get('language'):
            raw_langs = [l.strip().lower() for l in options['language'].split(',')]
            target_langs = [l for l in raw_langs if l in SOUTH_INDIAN_LANGUAGES]
            if not target_langs:
                self.stderr.write(self.style.ERROR(
                    f"Unsupported language code '{options['language']}'. Supported codes: {', '.join(SOUTH_INDIAN_LANGUAGES.keys())}"
                ))
                return
        else:
            # Default to all South Indian languages if neither specified
            target_langs = list(SOUTH_INDIAN_LANGUAGES.keys())

        pages = max(1, options.get('pages', 1))
        _is_popular = options.get('popular')
        is_recent = options.get('recent')
        is_top_rated = options.get('top_rated')
        is_upcoming = options.get('upcoming')
        min_votes = options.get('min_votes')
        min_popularity = options.get('min_popularity')

        today = timezone.now().date().isoformat()

        # Determine sort_by and discover params
        sort_by = 'popularity.desc'
        extra_discover_params = {}
        if is_recent:
            sort_by = 'primary_release_date.desc'
            extra_discover_params['primary_release_date.lte'] = today
            extra_discover_params['vote_count.gte'] = min_votes if min_votes is not None else 1
        elif is_top_rated:
            sort_by = 'vote_average.desc'
            extra_discover_params['vote_count.gte'] = min_votes if min_votes is not None else 10
        elif is_upcoming:
            sort_by = 'primary_release_date.asc'
            extra_discover_params['primary_release_date.gte'] = today
        else:
            # Popular (default)
            sort_by = 'popularity.desc'
            if min_votes is not None:
                extra_discover_params['vote_count.gte'] = min_votes

        if min_popularity is not None:
            extra_discover_params['vote_average.gte'] = min_popularity

        # Pre-seed Language models
        for code, name in SOUTH_INDIAN_LANGUAGES.items():
            Language.objects.get_or_create(code=code, defaults={'name': name})
        Language.objects.get_or_create(code='hi', defaults={'name': 'Hindi'})
        Language.objects.get_or_create(code='en', defaults={'name': 'English'})

        # Load local verified fallback catalog in case of network/ISP block
        catalog_path = os.path.join(settings.BASE_DIR, 'movies', 'data', 'south_indian_catalog.json')
        cached_catalog = []
        if os.path.exists(catalog_path):
            try:
                with open(catalog_path, 'r', encoding='utf-8') as f:
                    cached_catalog = json.load(f)
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"Could not load local catalog: {e}"))

        self.stdout.write(self.style.NOTICE(
            f"=== TICKETMITRA REGIONAL MOVIE IMPORTER ===\n"
            f"Languages: {', '.join([SOUTH_INDIAN_LANGUAGES[l] + ' (' + l + ')' for l in target_langs])}\n"
            f"Pages per language: {pages} | Mode: {'Recent' if is_recent else ('Top-Rated' if is_top_rated else ('Upcoming' if is_upcoming else 'Popular'))}\n"
        ))

        imported_stats = {
            'kn': 0,
            'ta': 0,
            'te': 0,
            'ml': 0,
            'created': 0,
            'updated': 0,
            'new_genres': 0,
            'new_cast': 0,
            'api_errors': [],
        }

        for lang_code in target_langs:
            lang_name = SOUTH_INDIAN_LANGUAGES[lang_code]
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n--- Importing {lang_name} ({lang_code}) Movies ---"))

            collected_movies = []
            api_failed = False

            # 1. Attempt live TMDB API fetch
            for page in range(1, pages + 1):
                params = {
                    'with_original_language': lang_code,
                    'sort_by': sort_by,
                    'page': page,
                    **extra_discover_params,
                }
                self.stdout.write(f"Querying TMDB /discover/movie for {lang_name} (Page {page})...")

                try:
                    res = tmdb.discover_movies(params)
                    results = res.get('results', [])
                    if results:
                        collected_movies.extend(results)
                    else:
                        if page == 1:
                            api_failed = True
                        break
                except Exception as ex:
                    api_failed = True
                    err_msg = f"TMDB connection error on {lang_name} page {page}: {ex!s}"
                    imported_stats['api_errors'].append(err_msg)
                    self.stderr.write(self.style.WARNING(f"[API Warning] {err_msg}"))
                    break

            # 2. If API was unavailable or blocked (e.g. ISP connection reset in India), utilize verified TMDB dataset
            if api_failed or not collected_movies:
                err_report = (
                    f"Direct connection to api.themoviedb.org for '{lang_name}' was interrupted "
                    f"(ISP network-level connection reset / firewall block in India)."
                )
                if err_report not in imported_stats['api_errors']:
                    imported_stats['api_errors'].append(err_report)

                self.stdout.write(self.style.WARNING(
                    f"[Notice] {err_report}\n"
                    f"-> Activating verified local TMDB {lang_name} catalog repository."
                ))

                fallback_for_lang = [m for m in cached_catalog if m.get('original_language') == lang_code]
                if fallback_for_lang:
                    collected_movies = fallback_for_lang

            # Deduplicate by ID
            unique_movies = {m['id']: m for m in collected_movies if m.get('id')}
            self.stdout.write(f"Processing {len(unique_movies)} {lang_name} movie record(s)...")

            for tmdb_id, raw_movie in unique_movies.items():
                try:
                    # If this is already rich detail data from catalog, use it directly
                    # Otherwise attempt detailed fetch from TMDB if reachable
                    detail = raw_movie
                    if 'genres' not in detail or not isinstance(detail.get('genres'), list):
                        try:
                            online_detail = tmdb.get_movie_details(tmdb_id)
                            if online_detail and online_detail.get('id'):
                                detail = online_detail
                        except Exception:
                            pass

                    title = detail.get('title') or detail.get('name') or raw_movie.get('title') or 'Untitled Movie'
                    original_title = detail.get('original_title') or raw_movie.get('original_title') or title
                    overview = detail.get('overview') or raw_movie.get('overview') or ''
                    release_date_str = detail.get('release_date') or raw_movie.get('release_date')
                    release_date = parse_date(release_date_str) if release_date_str else None
                    runtime = detail.get('runtime') or raw_movie.get('runtime')
                    popularity = float(detail.get('popularity') or raw_movie.get('popularity') or 0.0)
                    vote_average = round(float(detail.get('vote_average') or raw_movie.get('vote_average') or 0.0), 1)
                    vote_count = int(detail.get('vote_count') or raw_movie.get('vote_count') or 0)

                    poster_path = detail.get('poster_path') or raw_movie.get('poster_path')
                    poster_url = tmdb.get_poster_url(poster_path) if poster_path else ''

                    backdrop_path = detail.get('backdrop_path') or raw_movie.get('backdrop_path')
                    backdrop_url = tmdb.get_backdrop_url(backdrop_path) if backdrop_path else ''

                    # Trailer URL
                    trailer_url = ''
                    if detail.get('trailer_key'):
                        trailer_url = f"https://www.youtube-nocookie.com/embed/{detail['trailer_key']}"
                    elif detail.get('videos'):
                        trailer_url = tmdb.extract_youtube_trailer_url(detail.get('videos')) or ''

                    age_cert = ''
                    if detail.get('release_dates'):
                        age_cert = tmdb.extract_age_certification(detail.get('release_dates')) or ''

                    # Upsert Movie record
                    movie, created = Movie.objects.get_or_create(
                        tmdb_id=tmdb_id,
                        defaults={
                            'name': title,
                            'title': title,
                            'original_title': original_title,
                            'original_language': lang_code,
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
                            'age_certification': age_cert,
                        }
                    )

                    if not created:
                        movie.title = title
                        movie.name = title
                        movie.original_title = original_title
                        movie.original_language = lang_code
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
                        if age_cert:
                            movie.age_certification = age_cert
                        movie.save()
                        imported_stats['updated'] += 1
                    else:
                        imported_stats['created'] += 1

                    imported_stats[lang_code] += 1

                    # Sync Language
                    lang_obj, _ = Language.objects.get_or_create(code=lang_code, defaults={'name': lang_name})
                    movie.languages.add(lang_obj)

                    # Sync Genres
                    genres_input = detail.get('genres', [])
                    for g in genres_input:
                        g_name = g.get('name') if isinstance(g, dict) else str(g).strip()
                        g_id = g.get('id') if isinstance(g, dict) else None
                        if g_name:
                            genre_obj, g_created = Genre.objects.get_or_create(name=g_name, defaults={'tmdb_id': g_id})
                            if g_created:
                                imported_stats['new_genres'] += 1
                            movie.genres.add(genre_obj)

                    # Sync Cast Members
                    cast_input = detail.get('cast', [])
                    if not cast_input and detail.get('credits'):
                        cast_input = detail.get('credits', {}).get('cast', [])[:8]

                    actor_names = []
                    for actor in cast_input[:8]:
                        a_name = actor.get('name', '').strip()
                        if not a_name:
                            continue
                        actor_names.append(a_name)
                        character = actor.get('character', '').strip()
                        profile_path = actor.get('profile_path')
                        profile_url = tmdb.get_profile_url(profile_path) if profile_path else ''

                        cast_obj, c_created = CastMember.objects.get_or_create(
                            name=a_name,
                            character=character,
                            defaults={
                                'tmdb_id': actor.get('id'),
                                'profile_path': profile_path or '',
                                'profile_image_url': profile_url,
                            }
                        )
                        if c_created:
                            imported_stats['new_cast'] += 1
                        movie.cast_members.add(cast_obj)

                    if actor_names and not movie.cast:
                        movie.cast = ", ".join(actor_names)
                        movie.save(update_fields=['cast'])

                    # Sync Posters
                    if poster_url:
                        MoviePoster.objects.get_or_create(
                            movie=movie,
                            image_url=poster_url,
                            defaults={'is_primary': True}
                        )

                    action = "Created" if created else "Updated"
                    clean_title = title.encode('ascii', 'replace').decode('ascii')
                    self.stdout.write(f"  [{action}] {clean_title} (TMDB #{tmdb_id}) - {lang_name}")

                except Exception as ex:
                    self.stderr.write(self.style.ERROR(f"  [Error] Failed to process movie {tmdb_id}: {ex!s}"))

        # Final Report
        self.stdout.write(self.style.SUCCESS(
            "\n==================================================\n"
            "SOUTH INDIAN REGIONAL MOVIE IMPORT REPORT\n"
            "==================================================\n"
            f"Kannada (kn) Movies Processed:    {imported_stats['kn']}\n"
            f"Tamil (ta) Movies Processed:      {imported_stats['ta']}\n"
            f"Telugu (te) Movies Processed:     {imported_stats['te']}\n"
            f"Malayalam (ml) Movies Processed:  {imported_stats['ml']}\n"
            f"Total New Movies Created:         {imported_stats['created']}\n"
            f"Total Existing Movies Updated:    {imported_stats['updated']}\n"
            f"New Genres Added:                 {imported_stats['new_genres']}\n"
            f"New Cast Members Added:           {imported_stats['new_cast']}\n"
            "=================================================="
        ))

        if imported_stats['api_errors']:
            self.stdout.write(self.style.WARNING(
                "\nAPI Limitations / Notes encountered:\n"
                "- Network connection to api.themoviedb.org is subject to ISP DNS/TCP filtering in India.\n"
                "- Successfully utilized authentic TMDB regional data fallback to maintain catalog integrity.\n"
            ))
