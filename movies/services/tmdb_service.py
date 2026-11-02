import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TMDBServiceError(Exception):
    """Base exception for TMDB Service errors."""


class TMDBService:
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'TMDB_API_KEY', '').strip()
        self.base_url = getattr(settings, 'TMDB_BASE_URL', 'https://api.themoviedb.org/3').rstrip('/')
        self.image_base_url = getattr(settings, 'TMDB_IMAGE_BASE_URL', 'https://image.tmdb.org/t/p/').rstrip('/')
        self.poster_size = getattr(settings, 'TMDB_POSTER_SIZE', 'w500')
        self.backdrop_size = getattr(settings, 'TMDB_BACKDROP_SIZE', 'original')
        self.profile_size = getattr(settings, 'TMDB_PROFILE_SIZE', 'w185')

        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
        if self.api_key and self.api_key.startswith('eyJ'):
            self.session.headers['Authorization'] = f'Bearer {self.api_key}'

        from requests.adapters import HTTPAdapter
        from urllib3.util import Retry
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def _request(self, endpoint, params=None):
        if not self.api_key:
            logger.warning("TMDB API key is not configured. Returning empty response.")
            return {}

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query_params = {}
        if not self.api_key.startswith('eyJ'):
            query_params['api_key'] = self.api_key
        if params:
            query_params.update(params)

        try:
            response = self.session.get(url, params=query_params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"TMDB HTTP error for endpoint {endpoint}: {e.response.status_code}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"TMDB request failed for endpoint {endpoint}: {e!s}")
            return {}
        except ValueError as e:
            logger.error(f"Failed to parse TMDB JSON response: {e!s}")
            return {}

    def get_image_url(self, path, size='w500'):
        if not path:
            return None
        return f"{self.image_base_url}/{size}{path}"

    def get_poster_url(self, poster_path):
        return self.get_image_url(poster_path, self.poster_size)

    def get_backdrop_url(self, backdrop_path):
        return self.get_image_url(backdrop_path, self.backdrop_size)

    def get_profile_url(self, profile_path):
        return self.get_image_url(profile_path, self.profile_size)

    def search_movies(self, query, page=1):
        if not query:
            return {'results': []}
        return self._request('search/movie', {'query': query, 'page': page})

    def get_movie_details(self, tmdb_id, append_to_response='videos,credits,release_dates,images,watch/providers'):
        params = {}
        if append_to_response:
            params['append_to_response'] = append_to_response
        return self._request(f'movie/{tmdb_id}', params)

    def get_movie_credits(self, tmdb_id):
        return self._request(f'movie/{tmdb_id}/credits')

    def get_movie_videos(self, tmdb_id):
        return self._request(f'movie/{tmdb_id}/videos')

    def get_movie_genres(self):
        data = self._request('genre/movie/list')
        return data.get('genres', [])

    def get_popular_movies(self, page=1):
        return self._request('movie/popular', {'page': page})

    def get_trending_movies(self, time_window='week', page=1):
        return self._request(f'trending/movie/{time_window}', {'page': page})

    def get_now_playing_movies(self, page=1):
        return self._request('movie/now_playing', {'page': page})

    def get_upcoming_movies(self, page=1):
        return self._request('movie/upcoming', {'page': page})

    def get_top_rated_movies(self, page=1):
        return self._request('movie/top_rated', {'page': page})

    def discover_movies(self, params=None):
        """
        Discovers movies using TMDB /discover/movie endpoint with custom filters.
        Supports with_original_language, sort_by, region, release_dates, vote_count.gte, page.
        """
        return self._request('discover/movie', params or {})


    def extract_youtube_trailer_url(self, videos_data):
        """
        Extracts official YouTube trailer URL securely using youtube-nocookie.
        Only valid YouTube trailers are returned.
        """
        if not videos_data or not isinstance(videos_data, dict):
            return None

        results = videos_data.get('results', [])
        youtube_trailers = [
            v for v in results
            if v.get('site') == 'YouTube' and v.get('key')
        ]

        if not youtube_trailers:
            return None

        # Prioritize Official Trailer
        official_trailers = [
            v for v in youtube_trailers
            if v.get('type') == 'Trailer' and v.get('official') is True
        ]
        if official_trailers:
            key = official_trailers[0].get('key')
            return f"https://www.youtube-nocookie.com/embed/{key}"

        # Next prioritize any Trailer
        any_trailers = [v for v in youtube_trailers if v.get('type') == 'Trailer']
        if any_trailers:
            key = any_trailers[0].get('key')
            return f"https://www.youtube-nocookie.com/embed/{key}"

        # Next check Teasers
        teasers = [v for v in youtube_trailers if v.get('type') == 'Teaser']
        if teasers:
            key = teasers[0].get('key')
            return f"https://www.youtube-nocookie.com/embed/{key}"

        # Fallback to first valid YouTube video
        key = youtube_trailers[0].get('key')
        return f"https://www.youtube-nocookie.com/embed/{key}"

    def extract_age_certification(self, release_dates_data):
        """
        Extracts certification from release_dates payload.
        Prioritizes IN (India), then US, then any found non-empty certification.
        """
        if not release_dates_data or not isinstance(release_dates_data, dict):
            return None

        results = release_dates_data.get('results', [])
        country_certs = {}
        for country_info in results:
            country_code = country_info.get('iso_3166_1')
            for rd in country_info.get('release_dates', []):
                cert = rd.get('certification', '').strip()
                if cert and country_code not in country_certs:
                    country_certs[country_code] = cert

        # Prioritize IN then US
        if 'IN' in country_certs:
            return country_certs['IN']
        if 'US' in country_certs:
            return country_certs['US']
        if country_certs:
            return next(iter(country_certs.values()))

        return None

    def extract_indian_watch_providers(self, watch_data):
        """
        Extracts Indian OTT streaming providers and link from watch/providers payload.
        """
        if not watch_data or not isinstance(watch_data, dict):
            return {'has_ott': False, 'link': '', 'providers': []}

        results = watch_data.get('results', {})
        in_data = results.get('IN')
        if not in_data or not isinstance(in_data, dict):
            return {'has_ott': False, 'link': '', 'providers': []}

        link = in_data.get('link') or ''
        providers = []
        seen_names = set()

        for p_type in ['flatrate', 'rent', 'buy']:
            for item in in_data.get(p_type, []):
                name = item.get('provider_name', '').strip()
                logo_path = item.get('logo_path')
                if name and name not in seen_names:
                    seen_names.add(name)
                    logo_url = self.get_image_url(logo_path, 'w185') if logo_path else ''
                    providers.append({
                        'name': name,
                        'logo_url': logo_url,
                        'type': p_type
                    })

        has_ott = len(providers) > 0
        return {
            'has_ott': has_ott,
            'link': link,
            'providers': providers
        }

    def extract_indian_theatrical_release_info(self, release_dates_data):
        """
        Finds the Indian (iso_3166_1 == 'IN') release date if available.
        """
        if not release_dates_data or not isinstance(release_dates_data, dict):
            return {'release_date': None, 'certification': None}

        results = release_dates_data.get('results', [])
        for country in results:
            if country.get('iso_3166_1') == 'IN':
                for rd in country.get('release_dates', []):
                    d_str = rd.get('release_date')
                    cert = rd.get('certification')
                    date_val = None
                    if d_str:
                        date_val = d_str.split('T')[0]
                    return {'release_date': date_val, 'certification': cert}
        return {'release_date': None, 'certification': None}

    def import_or_update_movie(self, tmdb_id, set_status='CURRENT'):
        """
        Imports or updates a single movie from TMDB by its TMDB ID.
        Reuses existing Movie, Genre, Language, CastMember, MoviePoster models without duplicates.
        Ensures movies with future release dates cannot be set to 'CURRENT'.
        """
        from decimal import Decimal

        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from movies.models import CastMember, Genre, Language, Movie, MoviePoster

        detail = self.get_movie_details(tmdb_id, append_to_response='videos,credits,release_dates,images,watch/providers')
        if not detail or not detail.get('id'):
            raise ValueError(f"Could not retrieve details for TMDB ID {tmdb_id}.")

        title = detail.get('title') or detail.get('name') or 'Untitled Movie'
        original_title = detail.get('original_title') or ''
        overview = detail.get('overview') or ''
        release_date_str = detail.get('release_date')
        
        # Check Indian theatrical release date first
        indian_rel = self.extract_indian_theatrical_release_info(detail.get('release_dates'))
        if indian_rel.get('release_date'):
            release_date_str = indian_rel['release_date']

        release_date = parse_date(release_date_str) if release_date_str else None
        runtime = detail.get('runtime') or None
        popularity = float(detail.get('popularity') or 0.0)
        vote_average = Decimal(str(round(float(detail.get('vote_average') or 0.0), 1)))
        vote_count = int(detail.get('vote_count') or 0)
        orig_lang = (detail.get('original_language') or '').lower()

        poster_path = detail.get('poster_path')
        poster_url = self.get_poster_url(poster_path) if poster_path else ''

        backdrop_path = detail.get('backdrop_path')
        backdrop_url = self.get_backdrop_url(backdrop_path) if backdrop_path else ''

        trailer_url = self.extract_youtube_trailer_url(detail.get('videos')) or ''
        age_certification = self.extract_age_certification(detail.get('release_dates')) or (indian_rel.get('certification') or '')
        imdb_id = detail.get('imdb_id') or ''

        # Extract OTT Watch Providers in India
        watch_info = self.extract_indian_watch_providers(detail.get('watch/providers'))
        has_ott = watch_info['has_ott']
        ott_link = watch_info['link']
        ott_providers = watch_info['providers']

        # Extract director from credits
        director = ''
        credits_data = detail.get('credits', {})
        for member in credits_data.get('crew', []):
            if member.get('job') == 'Director':
                director = member.get('name', '').strip()
                break

        # Determine safe status dynamically
        today = timezone.now().date()
        target_status = set_status
        if release_date and release_date > today:
            target_status = 'UPCOMING'
        elif target_status == 'UPCOMING' and release_date and release_date <= today:
            target_status = 'CURRENT'

        movie, created = Movie.objects.get_or_create(
            tmdb_id=tmdb_id,
            defaults={
                'name': title,
                'title': title,
                'original_title': original_title,
                'original_language': orig_lang,
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
                'imdb_id': imdb_id,
                'director': director,
                'status': target_status,
                'is_in_active_catalog': True,
                'has_ott_release': has_ott,
                'ott_streaming_url': ott_link,
                'ott_providers': ott_providers,
            }
        )

        if not created:
            movie.name = title
            movie.title = title
            movie.original_title = original_title
            movie.original_language = orig_lang
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
            if imdb_id:
                movie.imdb_id = imdb_id
            if director:
                movie.director = director
            movie.status = target_status
            movie.is_in_active_catalog = True
            movie.has_ott_release = has_ott
            if ott_link:
                movie.ott_streaming_url = ott_link
            if ott_providers:
                movie.ott_providers = ott_providers
            movie.save()

        # Sync Genres without duplicates
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

        # Sync Languages without duplicates
        lang_map = {
            'en': 'English', 'kn': 'Kannada', 'ta': 'Tamil', 'te': 'Telugu',
            'hi': 'Hindi', 'ml': 'Malayalam', 'es': 'Spanish', 'fr': 'French',
            'ja': 'Japanese', 'ko': 'Korean', 'de': 'German', 'it': 'Italian',
            'zh': 'Chinese', 'bn': 'Bengali', 'mr': 'Marathi', 'pa': 'Punjabi'
        }
        lang_objs = []
        if orig_lang:
            l_name = lang_map.get(orig_lang, orig_lang.upper())
            l_obj, _ = Language.objects.get_or_create(code=orig_lang, defaults={'name': l_name})
            lang_objs.append(l_obj)
        for spoken in detail.get('spoken_languages', []):
            s_code = (spoken.get('iso_639_1') or '').lower()
            s_name = spoken.get('english_name') or spoken.get('name') or lang_map.get(s_code, s_code.upper())
            if s_code:
                l_obj, _ = Language.objects.get_or_create(code=s_code, defaults={'name': s_name})
                if l_obj not in lang_objs:
                    lang_objs.append(l_obj)
        if lang_objs:
            movie.languages.set(lang_objs)

        # Sync Cast Members (top 8) without duplicates
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
            char = actor.get('character', '').strip()
            p_path = actor.get('profile_path')
            p_url = self.get_profile_url(p_path) if p_path else ''
            cast_obj, _ = CastMember.objects.get_or_create(
                name=a_name,
                character=char,
                defaults={
                    'tmdb_id': a_id,
                    'profile_path': p_path or '',
                    'profile_image_url': p_url,
                }
            )
            cast_objs.append(cast_obj)
        if cast_objs:
            movie.cast_members.set(cast_objs)
        if cast_names:
            movie.cast = ", ".join(cast_names)
            movie.save(update_fields=['cast'])

        # Sync Posters without duplicates
        images_data = detail.get('images', {})
        posters_list = images_data.get('posters', [])[:4]
        if posters_list:
            for idx, p in enumerate(posters_list):
                p_path = p.get('file_path')
                if p_path:
                    p_url = self.get_poster_url(p_path)
                    if not MoviePoster.objects.filter(movie=movie, image_url=p_url).exists():
                        MoviePoster.objects.create(
                            movie=movie,
                            image_url=p_url,
                            is_primary=(idx == 0 and not movie.image)
                        )

        # Generate Groq AI Movie Analysis & Curatorial Verdict
        if not movie.ai_verdict:
            try:
                from movies.services.groq_service import GroqService
                gs = GroqService()
                if gs.is_available():
                    genre_names = ", ".join([g.name for g in genre_objs]) if genre_objs else ''
                    analysis = gs.analyze_movie(
                        title=title,
                        overview=overview,
                        release_date=str(release_date) if release_date else None,
                        genres=genre_names,
                        rating=vote_average,
                        is_upcoming=(target_status in ('UPCOMING', 'ADVANCE_BOOKING')),
                    )
                    movie.ai_verdict = analysis.get('verdict') or ''
                    movie.ai_analysis = analysis
                    movie.save(update_fields=['ai_verdict', 'ai_analysis'])
            except Exception as e:
                logger.warning(f"Could not generate Groq AI analysis for {movie.title}: {e}")

        return movie, created

