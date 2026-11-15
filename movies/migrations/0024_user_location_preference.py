from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('movies', '0023_movie_trailer_videos_and_video_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserLocationPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('city', models.CharField(blank=True, default='', max_length=100)),
                ('radius_km', models.PositiveSmallIntegerField(default=50)),
                ('location_method', models.CharField(default='city', max_length=20)),
                ('prompt_dismissed', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='location_preference', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
