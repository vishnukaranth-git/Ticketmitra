"""Conservative YouTube trailer discovery using verified movie metadata."""

import logging
import queue
import re
import threading
import unicodedata

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
_TRAILER_LOOKUP_QUEUE = queue.Queue()
_TRAILER_LOOKUP_LOCK = threading.Lock()
_TRAILER_LOOKUP_IDS = set()
_TRAILER_LOOKUP_WORKER = None

YOUTUBE_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
YOUTUBE_VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'
NO_MATCH = '__no_verified_trailer__'

LANGUAGE_NAMES = {
    'ar': 'Arabic', 'bn': 'Bengali', 'de': 'German', 'en': 'English',
    'es': 'Spanish', 'fr': 'French', 'gu': 'Gujarati', 'hi': 'Hindi',
    'ja': 'Japanese', 'kn': 'Kannada', 'ko': 'Korean', 'ml': 'Malayalam',
    'mr': 'Marathi', 'pa': 'Punjabi', 'ta': 'Tamil', 'te': 'Telugu',
    'ur': 'Urdu', 'zh': 'Chinese',
}
LANGUAGE_ALIASES = {
    'ar': ('arabic',), 'bn': ('bengali',), 'de': ('german',), 'en': ('english',),
    'es': ('spanish',), 'fr': ('french',), 'gu': ('gujarati',), 'hi': ('hindi',),
    'ja': ('japanese',), 'kn': ('kannada',), 'ko': ('korean',), 'ml': ('malayalam',),
    'mr': ('marathi',), 'pa': ('punjabi',), 'ta': ('tamil',), 'te': ('telugu',),
    'ur': ('urdu',), 'zh': ('chinese', 'mandarin'),
}

# Names of established film, studio and distributor channels. TMDB production
# company names are also checked for every candidate, so this list is only a
# secondary recognition signal and contains no movie-specific data.
RECOGNIZED_CHANNELS = (
    't-series', 'sony music', 'sony pictures', 'hombale films', 'zee studios',
    'zee music', 'dharma productions', 'yash raj films', 'yrf', 'sun pictures',
    'mythri movie makers', 'geetha arts', 'lyca productions', 'warner bros',
    'universal pictures', 'paramount pictures', 'marvel entertainment',
    'netflix india', 'prime video india', 'amazon prime video', 'lionsgate movies',
)


def _normalize(value):
    value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def _title_matches(candidate_title, movie_titles):
    candidate = f' {_normalize(candidate_title)} '
    for title in movie_titles:
        normalized = _normalize(title)
        if not normalized:
            continue
        if f' {normalized} ' in candidate:
            return True
        tokens = [token for token in normalized.split() if len(token) > 2]
        if len(tokens) >= 2 and sum(f' {token} ' in candidate for token in tokens) / len(tokens) >= 0.8:
            return True
    return False


def _has_expected_language(language, title, description, video_language=''):
    expected = (language or '').lower().split('-')[0]
    if not expected:
        return True
    expected_aliases = LANGUAGE_ALIASES.get(expected, ())
    metadata_language = (video_language or '').lower().split('-')[0]
    if metadata_language:
        if metadata_language == expected:
            return True
        # A different explicit audio language is a hard mismatch.
        if metadata_language != expected:
            return False

    text = f' {_normalize(title)} {_normalize(description)} '
    aliases = {_normalize(expected), *(_normalize(alias) for alias in expected_aliases)}
    aliases.discard('')
    if any(f' {alias} ' in text for alias in aliases):
        return True
    if expected == 'en':
        other_language_aliases = {
            _normalize(alias)
            for code, names in LANGUAGE_ALIASES.items() if code != 'en'
            for alias in names
        }
        return not any(alias and f' {alias} ' in text for alias in other_language_aliases)
    return False


def _channel_is_official(channel_title, production_companies):
    channel = _normalize(channel_title)
    if not channel:
        return False, 0

    for company in production_companies:
        normalized_company = _normalize(company)
        if len(normalized_company) >= 5 and (normalized_company in channel or channel in normalized_company):
            return True, 4

    for recognized in RECOGNIZED_CHANNELS:
        normalized = _normalize(recognized)
        if normalized and (normalized in channel or channel in normalized):
            return True, 3
    return False, 0


class YouTubeTrailerService:
    """Search for and validate a trailer; store only IDs returned by YouTube."""

    def __init__(self, api_key=None, tmdb_service=None):
        self.api_key = (api_key or getattr(settings, 'YOUTUBE_API_KEY', '')).strip()
        self.tmdb_service = tmdb_service

    def find_trailer_id(self, movie):
        trailer_ids = self.find_trailer_ids(movie)
        if not trailer_ids:
            return None
        first = trailer_ids[0]
        return first.get('video_id') if isinstance(first, dict) else first

    def find_trailer_ids(self, movie, force=False):
        if not self.api_key:
            return None

        identity = movie.tmdb_id or f'movie-{movie.pk}'
        cache_key = f'ticketmitra:youtube-trailer:v2:{identity}'
        if force:
            cache.delete(cache_key)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            if cached_result == NO_MATCH:
                return []
            if isinstance(cached_result, str):
                return [cached_result]
            return cached_result

        lock_key = f'{cache_key}:lock'
        if not cache.add(lock_key, True, timeout=45):
            return None

        try:
            return self._discover_and_cache(movie, cache_key)
        finally:
            cache.delete(lock_key)

    def _discover_and_cache(self, movie, cache_key):
        try:
            tmdb = self.tmdb_service
            if tmdb is None:
                from .tmdb_service import TMDBService
                tmdb = TMDBService()

            details = None
            if movie.tmdb_id and tmdb.api_key:
                details = tmdb.get_movie_details(movie.tmdb_id, append_to_response='')
                if details and details.get('id') != movie.tmdb_id:
                    details = None

            details = details or {}
            title = details.get('title') or details.get('original_title') or movie.title or movie.name
            original_title = details.get('original_title') or movie.original_title or title
            release_date = details.get('release_date') or (movie.release_date.isoformat() if movie.release_date else '')
            try:
                release_year = int(release_date[:4])
            except (TypeError, ValueError):
                return []
            language = (details.get('original_language') or movie.original_language or '').lower()
            if not language:
                return []
            language_name = LANGUAGE_NAMES.get(language, language)
            query = f'"{title}" {release_year} {language_name} official trailer'

            params = {
                'part': 'snippet',
                'type': 'video',
                'videoEmbeddable': 'true',
                'safeSearch': 'strict',
                'maxResults': 10,
                'q': query,
                'regionCode': 'IN',
                'key': self.api_key,
            }
            if re.fullmatch(r'[a-z]{2}', language):
                params['relevanceLanguage'] = language

            response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=10)
            if response.status_code != 200:
                logger.warning('YouTube trailer search returned HTTP %s for TMDB movie %s.', response.status_code, movie.tmdb_id)
                error_reason = str((response.json().get('error') or {}).get('errors', [{}])[0].get('reason', '')) if response.headers.get('content-type', '').startswith('application/json') else ''
                cache.set(cache_key, NO_MATCH, timeout=60 * 60 * 6 if error_reason in {'quotaExceeded', 'dailyLimitExceeded'} else 300)
                return []
            results = response.json().get('items', [])

            candidates = []
            titles = (title, original_title, movie.get_display_title(), movie.name)
            companies = [item.get('name', '') for item in (details.get('production_companies') or [])]
            for result in results:
                video_id = (result.get('id') or {}).get('videoId', '')
                snippet = result.get('snippet') or {}
                video_title = snippet.get('title', '')
                description = snippet.get('description', '')
                channel_title = snippet.get('channelTitle', '')
                normalized_title = _normalize(video_title)
                metadata_text = f'{video_title} {description}'

                if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    continue
                if not _title_matches(video_title, titles):
                    continue
                if 'official' not in normalized_title:
                    continue
                if any(term in _normalize(video_title) for term in ('song', 'promo', 'clip', 'reaction', 'review', 'fan made', 'fanmade')):
                    continue
                if 'trailer' not in normalized_title and 'teaser' not in normalized_title:
                    continue

                years = {int(year) for year in re.findall(r'\b(?:19|20)\d{2}\b', metadata_text)}
                published = snippet.get('publishedAt', '')
                try:
                    published_year = int(published[:4])
                except (TypeError, ValueError):
                    published_year = None
                year_match = release_year in years or (
                    published_year is not None and release_year - 2 <= published_year <= release_year + 1
                )
                if not year_match:
                    continue

                channel_official, channel_score = _channel_is_official(channel_title, companies)
                if not channel_official:
                    continue
                candidates.append({
                    'video_id': video_id,
                    'channel_id': snippet.get('channelId', ''),
                    'channel_score': channel_score,
                    'title': video_title,
                    'description': description,
                    'published_year': published_year or 0,
                    'video_type': 'Teaser' if 'teaser' in _normalize(video_title) else 'Trailer',
                    'channel_title': channel_title,
                })

            selected = self._verify_candidate_languages(candidates, language)
            if selected:
                cache.set(cache_key, selected, timeout=60 * 60 * 24 * 30)
                return selected

            cache.set(cache_key, NO_MATCH, timeout=60 * 60 * 12)
            return []
        except requests.RequestException as exc:
            # Do not log request exception text; it can contain the API key URL.
            logger.warning('YouTube trailer discovery request failed (%s) for TMDB movie %s.', type(exc).__name__, movie.tmdb_id)
            cache.set(cache_key, NO_MATCH, timeout=300)
            return []
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning('Could not validate YouTube trailer metadata (%s) for TMDB movie %s.', type(exc).__name__, movie.tmdb_id)
            cache.set(cache_key, NO_MATCH, timeout=300)
            return []

    def _verify_candidate_languages(self, candidates, expected_language):
        if not candidates:
            return []
        candidates.sort(key=lambda item: (item['video_type'] == 'Trailer', item['channel_score'], item['published_year']), reverse=True)
        ids = [candidate['video_id'] for candidate in candidates[:10]]
        params = {'part': 'snippet', 'id': ','.join(ids), 'key': self.api_key}
        response = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=8)
        if response.status_code != 200:
            logger.warning('YouTube trailer metadata verification returned HTTP %s.', response.status_code)
            raise requests.RequestException('YouTube trailer metadata verification failed.')

        snippets = {
            item.get('id'): item.get('snippet') or {}
            for item in response.json().get('items', [])
        }
        verified = []
        seen = set()
        for candidate in candidates:
            snippet = snippets.get(candidate['video_id'])
            if not snippet:
                continue
            audio_language = snippet.get('defaultAudioLanguage') or snippet.get('defaultLanguage') or ''
            if _has_expected_language(
                expected_language,
                candidate['title'],
                candidate['description'],
                audio_language,
            ):
                video_id = candidate['video_id']
                if video_id not in seen:
                    verified.append({
                        'video_id': video_id,
                        'title': candidate['title'],
                        'channel_title': candidate.get('channel_title', ''),
                        'video_type': candidate.get('video_type', 'Trailer'),
                        'channel_score': candidate.get('channel_score', 0),
                    })
                    seen.add(video_id)
                if len(verified) >= 3:
                    break
        return verified


def fetch_and_store_movie_trailers(movie, *, force=False):
    """Discover verified official trailers and persist their YouTube IDs and embed URLs."""
    if not force and movie.get_trailer_embed_url():
        return False

    service = YouTubeTrailerService()
    matches = service.find_trailer_ids(movie, force=force)
    if not matches:
        return False

    videos = [
        {
            'video_id': item['video_id'],
            'title': item['title'],
            'channel_title': item.get('channel_title', ''),
            'video_type': item.get('video_type', 'Trailer'),
            'url': f"https://www.youtube-nocookie.com/embed/{item['video_id']}",
        }
        for item in matches
    ]
    primary = next((item for item in videos if item['video_type'] == 'Trailer'), videos[0])
    movie.trailer_videos = videos
    movie.trailer_video_id = primary['video_id']
    movie.trailer_url = primary['url']
    movie.save(update_fields=['trailer_videos', 'trailer_video_id', 'trailer_url', 'updated_at'])
    return True


def queue_movie_trailer_lookup(movie_id, *, force=False):
    """Queue asynchronously when a worker is configured; serialize local lookups in dev."""
    global _TRAILER_LOOKUP_WORKER
    from django.conf import settings

    broker_url = str(getattr(settings, 'CELERY_BROKER_URL', 'memory://'))
    if not broker_url.startswith('memory://'):
        try:
            from movies.tasks import fetch_movie_trailer_task
            fetch_movie_trailer_task.delay(movie_id, force=force)
            return True
        except Exception as exc:
            logger.warning('Could not queue trailer lookup (%s); using local background thread.', type(exc).__name__)

    queue_id = (movie_id, bool(force))
    with _TRAILER_LOOKUP_LOCK:
        if queue_id in _TRAILER_LOOKUP_IDS:
            return True
        _TRAILER_LOOKUP_IDS.add(queue_id)
        _TRAILER_LOOKUP_QUEUE.put(queue_id)
        if _TRAILER_LOOKUP_WORKER is None or not _TRAILER_LOOKUP_WORKER.is_alive():
            _TRAILER_LOOKUP_WORKER = threading.Thread(
                target=_run_local_trailer_queue,
                name='ticketmitra-youtube-trailer-worker',
                daemon=True,
            )
            _TRAILER_LOOKUP_WORKER.start()
    return True


def _run_local_trailer_queue():
    from django.db import close_old_connections
    from movies.models import Movie

    while True:
        movie_id, force = _TRAILER_LOOKUP_QUEUE.get()
        try:
            close_old_connections()
            movie = Movie.objects.get(pk=movie_id)
            fetch_and_store_movie_trailers(movie, force=force)
        except Movie.DoesNotExist:
            pass
        except Exception as exc:
            logger.warning('Trailer lookup failed for movie %s (%s).', movie_id, type(exc).__name__)
        finally:
            close_old_connections()
            with _TRAILER_LOOKUP_LOCK:
                _TRAILER_LOOKUP_IDS.discard((movie_id, force))
            _TRAILER_LOOKUP_QUEUE.task_done()


def validate_youtube_video(video_id, expected_language=''):
    """Confirm that a manually supplied video is available and matches its language."""
    api_key = getattr(settings, 'YOUTUBE_API_KEY', '').strip()
    if not api_key or not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(video_id or '')):
        return False
    try:
        response = requests.get(
            YOUTUBE_VIDEOS_URL,
            params={'part': 'snippet', 'id': video_id, 'key': api_key},
            timeout=8,
        )
        if response.status_code != 200:
            return False
        item = next(iter(response.json().get('items', [])), None)
        if not item:
            return False
        snippet = item.get('snippet') or {}
        return _has_expected_language(
            expected_language,
            snippet.get('title', ''),
            snippet.get('description', ''),
            snippet.get('defaultAudioLanguage') or snippet.get('defaultLanguage') or '',
        )
    except (requests.RequestException, ValueError, TypeError):
        return False
