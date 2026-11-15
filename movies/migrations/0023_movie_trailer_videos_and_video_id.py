from django.db import migrations, models
import re
from urllib.parse import parse_qs, urlparse


def populate_existing_trailer_ids(apps, schema_editor):
    Movie = apps.get_model('movies', 'Movie')
    database = schema_editor.connection.alias
    for movie in Movie.objects.using(database).exclude(trailer_url__isnull=True).exclude(trailer_url='').iterator(chunk_size=200):
        parsed = urlparse(movie.trailer_url.strip())
        host = (parsed.hostname or '').lower()
        if host not in {
            'youtube.com', 'www.youtube.com', 'm.youtube.com',
            'youtube-nocookie.com', 'www.youtube-nocookie.com',
            'youtu.be', 'www.youtu.be',
        }:
            continue
        if host.endswith('youtu.be'):
            video_id = parsed.path.strip('/').split('/')[0]
        else:
            video_id = parse_qs(parsed.query).get('v', [None])[0]
            if not video_id:
                match = re.search(r'/(?:embed|v|shorts|live)/([A-Za-z0-9_-]{11})(?:/|$)', parsed.path)
                video_id = match.group(1) if match else None
        if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            continue
        trailer = {
            'video_id': video_id,
            'title': f'{movie.title or movie.name} Official Trailer',
            'video_type': 'Trailer',
            'url': f'https://www.youtube-nocookie.com/embed/{video_id}',
        }
        Movie.objects.using(database).filter(pk=movie.pk).update(
            trailer_video_id=video_id,
            trailer_videos=[trailer],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0022_alter_seat_screen_alter_seat_theater_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='movie',
            name='trailer_video_id',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='movie',
            name='trailer_videos',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(populate_existing_trailer_ids, migrations.RunPython.noop),
    ]
