import datetime
import time
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from movies.models import Movie
from movies.services.tmdb_service import TMDBService


class Command(BaseCommand):
    help = 'Refresh verified regional theatrical movie records from TMDB.'

    def add_arguments(self, parser):
        parser.add_argument('--pages', type=int, default=3, help='Pages per regional endpoint/discovery (1-5).')
        parser.add_argument('--regions', default='IN,US,GB,AU', help='Comma-separated TMDB regions, e.g. IN,US,GB,AU.')
        parser.add_argument('--dry-run', action='store_true', help='Fetch and classify without writing records.')

    def handle(self, *args, **options):
        tmdb = TMDBService()
        if not tmdb.api_key and not tmdb.access_token:
            self.stderr.write(self.style.ERROR('TMDB credentials are not configured (TMDB_API_KEY or TMDB_ACCESS_TOKEN).'))
            return
        pages = min(5, max(1, options['pages']))
        dry_run = options['dry_run']
        today = timezone.localdate()
        regions = tuple(dict.fromkeys(code.strip().upper() for code in options['regions'].split(',') if code.strip()))
        if not regions:
            self.stderr.write(self.style.ERROR('At least one TMDB region is required.'))
            return
        languages = ('kn', 'ta', 'te', 'ml', 'hi', 'bn', 'mr', 'en')
        candidates = {}
        endpoint_counts = Counter()
        detail_statuses = Counter()
        errors = Counter()

        def fetch(endpoint, params):
            data = tmdb._request(endpoint, params)
            status = tmdb.last_status_code
            results = data.get('results', []) if isinstance(data, dict) else []
            endpoint_counts[endpoint] += len(results)
            self.stdout.write(f'API endpoint=/{endpoint} status={status or tmdb.last_error or "unknown"} results={len(results)}')
            if not data and tmdb.last_error:
                errors[tmdb.last_error] += 1
            return data

        # Explicit live authentication and transport check before collecting feeds.
        probe_region = 'IN' if 'IN' in regions else regions[0]
        probe = fetch('configuration', {})
        if not probe or not isinstance(probe, dict) or 'images' not in probe:
            self.stderr.write(self.style.ERROR(f'TMDB configuration check failed (HTTP {tmdb.last_status_code or tmdb.last_error or "unknown"}); database left unchanged.'))
            return
        probe = fetch('movie/now_playing', {'region': probe_region, 'language': 'en-IN' if probe_region == 'IN' else 'en-US', 'page': 1})
        if not probe and (not tmdb.last_status_code or int(tmdb.last_status_code) >= 400):
            self.stderr.write(self.style.ERROR(f'TMDB now-playing check failed (HTTP {tmdb.last_status_code or tmdb.last_error or "unknown"}); database left unchanged.'))
            return

        for region in regions:
            for endpoint, status in (('movie/now_playing', 'CURRENT'), ('movie/upcoming', 'UPCOMING')):
                for page in range(1, pages + 1):
                    data = probe if endpoint == 'movie/now_playing' and region == probe_region and page == 1 else fetch(endpoint, {'region': region, 'language': 'en-IN' if region == 'IN' else 'en-US', 'page': page})
                    if data.get('results') is None:
                        continue
                    for item in data.get('results', []):
                        mid = item.get('id')
                        if mid:
                            if status == 'CURRENT':
                                candidates[mid] = 'CURRENT'
                            else:
                                candidates.setdefault(mid, status)
                    if page >= int(data.get('total_pages') or 1):
                        break
            if region == 'IN':
                for lang in languages:
                    for date_key, status in (('primary_release_date.lte', 'CURRENT'), ('primary_release_date.gte', 'UPCOMING')):
                        params = {'region': region, 'with_original_language': lang, 'sort_by': 'popularity.desc', 'with_release_type': '2|3'}
                        if status == 'CURRENT':
                            params.update({date_key: str(today), 'primary_release_date.gte': str(today - datetime.timedelta(days=60))})
                        else:
                            params[date_key] = str(today + datetime.timedelta(days=1))
                        for page in range(1, pages + 1):
                            data = fetch('discover/movie', {**params, 'page': page})
                            for item in data.get('results', []):
                                if item.get('id'):
                                    if status == 'CURRENT':
                                        candidates[item['id']] = 'CURRENT'
                                    else:
                                        candidates.setdefault(item['id'], status)
                            if page >= int(data.get('total_pages') or 1):
                                break

        if not candidates:
            self.stdout.write('No candidate movies returned; no database changes made.')
            return

        counts = Counter()
        reasons = Counter()
        current_feed_ids = {mid for mid, status in candidates.items() if status == 'CURRENT'}
        for index, (mid, feed_status) in enumerate(candidates.items(), 1):
            try:
                detail = tmdb.get_movie_details(mid)
                if not detail or detail.get('id') != mid:
                    counts['skipped'] += 1; reasons['details_missing'] += 1; continue
                detail_statuses[str(tmdb.last_status_code or tmdb.last_error or 'unknown')] += 1
                release_map = tmdb.extract_theatrical_release_dates(detail.get('release_dates'))
                theatrical_dates = [entry['date'] for values in release_map.values() for entry in values]
                if not theatrical_dates:
                    counts['skipped'] += 1; reasons['no_verified_theatrical_date'] += 1; continue
                if not detail.get('poster_path'):
                    counts['skipped'] += 1; reasons['missing_poster'] += 1; continue
                title = (detail.get('title') or '').strip()
                if not title:
                    counts['skipped'] += 1; reasons['missing_title'] += 1; continue
                existed = Movie.objects.filter(tmdb_id=mid).exists()
                status = feed_status
                # Upcoming classification is valid only while the theatrical date is future.
                if status == 'UPCOMING' and any(date['date'] <= str(today) for values in release_map.values() for date in values):
                    status = 'CURRENT'
                if dry_run:
                    counts['updated' if existed else 'would_create'] += 1
                    continue
                for attempt in range(3):
                    try:
                        with transaction.atomic():
                            movie, created = tmdb.import_or_update_movie(
                                mid, set_status=status, detail=detail, generate_ai_analysis=False
                            )
                            if movie.status != status:
                                movie.status = status
                                movie.save(update_fields=['status'])
                        break
                    except OperationalError:
                        if attempt == 2:
                            raise
                        time.sleep(0.25 * (2 ** attempt))
                counts['created' if created else 'updated'] += 1
                counts['valid_posters'] += bool(movie.poster_url)
                counts['valid_ratings'] += bool(movie.vote_count and movie.tmdb_rating)
            except Exception as exc:
                counts['skipped'] += 1
                reason = type(exc).__name__
                if isinstance(exc, OperationalError):
                    reason += ': ' + ' '.join(str(exc).split())[:120]
                reasons[reason] += 1
            if index % 25 == 0:
                self.stdout.write(f'Processed {index}/{len(candidates)}')

        # Keep historical rows and booking/payment references. Only end stale
        # current catalogue entries after the 60-day discovery window when no
        # supported regional Now Playing/Discover feed or verified future showtime
        # still supports theatrical relevance.
        stale_cutoff = today - datetime.timedelta(days=60)
        if current_feed_ids:
            stale_current = Movie.objects.filter(
                is_in_active_catalog=True,
                is_ott_only=False,
                tmdb_id__isnull=False,
                status='CURRENT',
                release_date__lt=stale_cutoff,
            ).exclude(tmdb_id__in=current_feed_ids).exclude(
                Q(theaters__active=True, theaters__admin_verified=True, theaters__time__gte=timezone.now(),
                  theaters__operational_status__in=('SCHEDULED', 'BOOKING_OPEN'),
                  theaters__screen__active=True, theaters__screen__operational_status='ACTIVE')
            ).distinct()
            counts['stale_current'] = stale_current.count()
            if not dry_run and counts['stale_current']:
                stale_current.update(status='ENDED')
                from movies.services.ranking_service import invalidate_movie_ranking_cache
                invalidate_movie_ranking_cache()

        self.stdout.write('Refresh summary:')
        self.stdout.write(f'  Candidates={len(candidates)} imported={counts["created"] + counts["updated"]} created={counts["created"]} updated={counts["updated"]} skipped={counts["skipped"]}')
        self.stdout.write(f'  Detail endpoint=/movie/{{id}} status counts={dict(detail_statuses)}')
        imported = counts['created'] + counts['updated']
        self.stdout.write(f'  Valid posters={counts["valid_posters"]} missing posters={max(0, imported - counts["valid_posters"])}')
        self.stdout.write(f'  Valid ratings={counts["valid_ratings"]} missing ratings={max(0, imported - counts["valid_ratings"])}')
        self.stdout.write(f'  Current={Movie.objects.filter(is_in_active_catalog=True, status="CURRENT").count()} upcoming={Movie.objects.filter(is_in_active_catalog=True, status="UPCOMING").count()}')
        self.stdout.write(f'  Stale current records marked ENDED (preserved)={counts["stale_current"]}')
        if reasons:
            self.stdout.write('  Skip reasons=' + ', '.join(f'{key}:{value}' for key, value in sorted(reasons.items())))
        if errors:
            self.stdout.write('  API errors=' + ', '.join(f'{key}:{value}' for key, value in sorted(errors.items())))
        if dry_run:
            self.stdout.write('  Dry run: no database writes.')
