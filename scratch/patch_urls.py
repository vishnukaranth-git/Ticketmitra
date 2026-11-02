import os

urls_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'movies', 'urls.py')
with open(urls_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = "    path('api/nearby-theaters/', views.nearby_theaters_api, name='nearby_theaters_api'),\n]"
target_crlf = "    path('api/nearby-theaters/', views.nearby_theaters_api, name='nearby_theaters_api'),\r\n]"

replacement = """    path('api/nearby-theaters/', views.nearby_theaters_api, name='nearby_theaters_api'),

    # Automated Weekly Friday Movies Discovery & Refresh APIs
    path('api/weekly-movies/', views.weekly_movies_api, name='api_weekly_movies'),
    path('api/weekly-movies/refresh/', views.trigger_weekly_sync_api, name='api_trigger_weekly_sync'),
]"""

if 'api/weekly-movies/' not in content:
    if target_crlf in content:
        content = content.replace(target_crlf, replacement.replace('\n', '\r\n'))
    elif target in content:
        content = content.replace(target, replacement)
    with open(urls_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated urls.py successfully.")
else:
    print("Already in urls.py.")

