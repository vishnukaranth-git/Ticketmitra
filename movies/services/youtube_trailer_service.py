"""Conservative YouTube trailer discovery using verified movie metadata."""

import logging
import re
import unicodedata

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

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
    return any(f' {alias} ' in text for alias in aliases)


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
        if not self.api_key or not movie.tmdb_id:
            return None

        cache_key = f'ticketmitra:youtube-trailer:v1:{movie.tmdb_id}'
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return None if cached_result == NO_MATCH else cached_result

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

            if not tmdb.api_key:
                return None
            details = tmdb.get_movie_details(movie.tmdb_id, append_to_response='')
            if not details or details.get('id') != movie.tmdb_id:
                return None

            title = details.get('title') or details.get('original_title') or movie.title or movie.name
            original_title = details.get('original_title') or movie.original_title or title
            release_date = details.get('release_date') or (movie.release_date.isoformat() if movie.release_date else '')
            try:
                release_year = int(release_date[:4])
            except (TypeError, ValueError):
                return None
            language = (details.get('original_language') or movie.original_language or '').lower()
            if not language:
                return None
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
                cache.set(cache_key, NO_MATCH, timeout=300)
                return None
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
                metadata_text = f'{video_title} {description}'
                normalized_text = _normalize(metadata_text)

                if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    continue
                if not _title_matches(video_title, titles):
                    continue
                if 'trailer' not in normalized_text or 'official' not in normalized_text:
                    continue
                if any(term in _normalize(video_title) for term in ('teaser', 'song', 'promo', 'clip', 'reaction')):
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
                })

            selected_id = self._verify_candidate_languages(candidates, language)
            if selected_id:
                cache.set(cache_key, selected_id, timeout=60 * 60 * 24 * 30)
                return selected_id

            cache.set(cache_key, NO_MATCH, timeout=60 * 60 * 12)
            return None
        except requests.RequestException as exc:
            # Do not log request exception text; it can contain the API key URL.
            logger.warning('YouTube trailer discovery request failed (%s) for TMDB movie %s.', type(exc).__name__, movie.tmdb_id)
            cache.set(cache_key, NO_MATCH, timeout=300)
            return None
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning('Could not validate YouTube trailer metadata (%s) for TMDB movie %s.', type(exc).__name__, movie.tmdb_id)
            cache.set(cache_key, NO_MATCH, timeout=300)
            return None

    def _verify_candidate_languages(self, candidates, expected_language):
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item['channel_score'], item['published_year']), reverse=True)
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
                return candidate['video_id']
        return None
