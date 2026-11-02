import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from movies.models import CinemaVenue, Genre, Language, Movie, Screen, Seat, Theater


class Command(BaseCommand):
    help = "Seed or synchronize movies and venues to match the TicketMitra editorial mockup UI"

    def handle(self, *args, **options):
        self.stdout.write("Seeding editorial mockup data...")
        today = timezone.now().date()
        future_showtime = timezone.now() + datetime.timedelta(hours=4)

        # 1. Ensure Languages
        languages = {
            'ml': Language.objects.get_or_create(code='ml', defaults={'name': 'Malayalam'})[0],
            'kn': Language.objects.get_or_create(code='kn', defaults={'name': 'Kannada'})[0],
            'ta': Language.objects.get_or_create(code='ta', defaults={'name': 'Tamil'})[0],
            'te': Language.objects.get_or_create(code='te', defaults={'name': 'Telugu'})[0],
            'hi': Language.objects.get_or_create(code='hi', defaults={'name': 'Hindi'})[0],
            'en': Language.objects.get_or_create(code='en', defaults={'name': 'English'})[0],
        }

        # 2. Ensure Genres
        genres = {
            'Thriller': Genre.objects.get_or_create(name='Thriller')[0],
            'Crime': Genre.objects.get_or_create(name='Crime')[0],
            'Action': Genre.objects.get_or_create(name='Action')[0],
            'Drama': Genre.objects.get_or_create(name='Drama')[0],
            'Sci-Fi': Genre.objects.get_or_create(name='Sci-Fi')[0],
            'Romance': Genre.objects.get_or_create(name='Romance')[0],
            'Adventure': Genre.objects.get_or_create(name='Adventure')[0],
            'Epic': Genre.objects.get_or_create(name='Epic')[0],
        }

        # 3. Ensure Venues & Screens
        venues_data = [
            {
                'name': 'INOX Galleria Mall',
                'address': 'Yelahanka Rd, Bengaluru',
                'lat': 13.1007,
                'lon': 77.5963,
                'formats': [('Audi 1 (IMAX)', 'IMAX', 220), ('Audi 2', 'STANDARD', 180)],
            },
            {
                'name': 'PVR Vega City',
                'address': 'Bannerghatta Rd, Bengaluru',
                'lat': 12.9081,
                'lon': 77.5997,
                'formats': [('Audi 1 (4DX)', '4DX', 160), ('Audi 2 (GOLD)', 'GOLD', 120)],
            },
            {
                'name': 'Cinépolis Nexus Mall',
                'address': 'Koramangala 7th, Bengaluru',
                'lat': 12.9352,
                'lon': 77.6145,
                'formats': [('Audi 1', 'STANDARD', 200), ('Audi 2 (GOLD)', 'GOLD', 100)],
            },
        ]

        created_screens = []
        for vd in venues_data:
            venue, _ = CinemaVenue.objects.get_or_create(
                name=vd['name'],
                defaults={
                    'address': vd['address'],
                    'city': 'Bengaluru',
                    'state': 'Karnataka',
                    'latitude': vd['lat'],
                    'longitude': vd['lon'],
                    'active': True,
                }
            )
            venue.address = vd['address']
            venue.latitude = vd['lat']
            venue.longitude = vd['lon']
            venue.active = True
            venue.save()

            for scr_name, scr_type, cap in vd['formats']:
                screen, _ = Screen.objects.get_or_create(
                    theater_name=vd['name'],
                    name=scr_name,
                    defaults={'screen_type': scr_type, 'capacity': cap, 'active': True}
                )
                screen.screen_type = scr_type
                screen.capacity = cap
                screen.active = True
                screen.save()
                created_screens.append(screen)

        # 4. Hero Featured Premiere & Trending Movies
        movies_spec = [
            {
                'title': 'Drishyam 3: The Ultimate Reckoning',
                'name': 'Drishyam 3',
                'lang': 'ml',
                'add_langs': ['hi', 'kn', 'ta'],
                'genres': ['Crime', 'Thriller'],
                'rating': 9.4,
                'runtime': 165,
                'cert': 'UA 16+',
                'popularity': 999.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=12),
                'poster_url': 'https://image.tmdb.org/t/p/w500/t6HIqrRAclMCA60NsSmeqe9RmNV.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/6XJTV7NqZqU0470v2yA6N0tEaJp.jpg',
                'desc': 'Six years after the case was cold-sealed, an unexpected excavation near the old quarry area risks a re-trial missing clue. Georgekutty faces his final, most dangerous cerebral battle to protect his family as stern forensics close in.',
            },
            {
                'title': 'Kantara: Chapter 1',
                'name': 'Kantara: Chapter 1',
                'lang': 'kn',
                'add_langs': ['hi', 'te', 'ta', 'ml'],
                'genres': ['Action', 'Epic'],
                'rating': 9.7,
                'runtime': 160,
                'cert': 'UA 16+',
                'popularity': 980.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=20),
                'poster_url': 'https://image.tmdb.org/t/p/w500/xXpB0Fq9FqG5qVb0vK0J4G8W6P.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/6XJTV7NqZqU0470v2yA6N0tEaJp.jpg',
                'desc': 'The mythic prequel delving deep into the folklore of Kadubettu, exploring the origin of the celestial divine spirit and the eternal battle between human arrogance and divine guardianship.',
            },
            {
                'title': 'The Odyssey',
                'name': 'The Odyssey',
                'lang': 'en',
                'add_langs': ['hi'],
                'genres': ['Epic', 'Adventure'],
                'rating': 8.9,
                'runtime': 155,
                'cert': 'UA 13+',
                'popularity': 950.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=15),
                'poster_url': 'https://image.tmdb.org/t/p/w500/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/h3jLam0blH2pf5G5Qba2vsJt5eG.jpg',
                'desc': 'A monumental historical odyssey charting the perilous voyage across mythical Mediterranean waters, facing monstrous trials and divine intervention.',
            },
            {
                'title': 'Dune: Part Two',
                'name': 'Dune: Part Two',
                'lang': 'en',
                'add_langs': ['hi'],
                'genres': ['Sci-Fi', 'Action'],
                'rating': 9.1,
                'runtime': 166,
                'cert': 'UA 13+',
                'popularity': 930.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=35),
                'poster_url': 'https://image.tmdb.org/t/p/w500/8b8Rnxud8Hu0yt5SoHQbm4CYY5C.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg',
                'desc': 'Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family.',
            },
            {
                'title': 'Pushpa 2: The Rule',
                'name': 'Pushpa 2: The Rule',
                'lang': 'te',
                'add_langs': ['hi', 'kn', 'ta', 'ml'],
                'genres': ['Action', 'Thriller'],
                'rating': 9.4,
                'runtime': 175,
                'cert': 'A',
                'popularity': 910.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=10),
                'poster_url': 'https://image.tmdb.org/t/p/w500/b1x6mwtR7jYgZ0F8Y3I4pP2gB4s.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/87W6wN5T9fE7s4A5JkL2e9G2k4A.jpg',
                'desc': 'Pushpa Raj solidifies his rule across international red sandalwood syndicates while confronting unyielding police retaliation.',
            },
            # Now Showing
            {
                'title': 'The Goat Life',
                'name': 'The Goat Life',
                'lang': 'ml',
                'add_langs': ['ta', 'te', 'hi'],
                'genres': ['Drama', 'Adventure'],
                'rating': 8.7,
                'runtime': 173,
                'cert': 'UA 16+',
                'popularity': 880.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=40),
                'poster_url': 'https://image.tmdb.org/t/p/w500/z1P053PZtK5b1J1Hk0h1oY9zX9k.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/2KGxQFV9Wp1iCrPB6rV85qwR9pf.jpg',
                'desc': 'The real-life survival story of Najeeb, an Indian migrant worker stranded in the remote deserts of Saudi Arabia herding goats under harrowing conditions.',
            },
            {
                'title': 'Sapta Sagaradaache Ello',
                'name': 'Sapta Sagaradaache Ello',
                'lang': 'kn',
                'add_langs': ['ta', 'te', 'ml'],
                'genres': ['Romance', 'Drama'],
                'rating': 8.8,
                'runtime': 142,
                'cert': 'U',
                'popularity': 870.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=50),
                'poster_url': 'https://image.tmdb.org/t/p/w500/p9Z0hXy8d8eX4V3gY3y0d8E1n7v.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/6XJTV7NqZqU0470v2yA6N0tEaJp.jpg',
                'desc': 'An intimate, poignant saga of deep yearning between Manu and Priya, navigating sacrifices that ripple across decades like boundless ocean waves.',
            },
            {
                'title': 'Maharaja',
                'name': 'Maharaja',
                'lang': 'ta',
                'add_langs': ['te', 'hi'],
                'genres': ['Thriller', 'Crime'],
                'rating': 8.6,
                'runtime': 140,
                'cert': 'UA 16+',
                'popularity': 860.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=45),
                'poster_url': 'https://image.tmdb.org/t/p/w500/bJ88Q4nKj2z2R5f6f4H8l8F9q3e.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/6XJTV7NqZqU0470v2yA6N0tEaJp.jpg',
                'desc': 'A quiet barber files a bizarre complaint reporting his home dustbin "Lakshmi" missing, unraveling a labyrinth of deep dark retribution.',
            },
            {
                'title': 'Civil War',
                'name': 'Civil War',
                'lang': 'en',
                'add_langs': ['hi'],
                'genres': ['Action', 'Drama'],
                'rating': 7.8,
                'runtime': 109,
                'cert': 'A',
                'popularity': 850.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=60),
                'poster_url': 'https://image.tmdb.org/t/p/w500/sh7Rg8Er3tFcN9BpKIPOMvALgZd.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/h3jLam0blH2pf5G5Qba2vsJt5eG.jpg',
                'desc': 'In a near-future dystopian America, a team of military-embedded journalists race against time to reach DC before rebel factions descend upon the White House.',
            },
            {
                'title': 'Manjummel Boys',
                'name': 'Manjummel Boys',
                'lang': 'ml',
                'add_langs': ['ta'],
                'genres': ['Thriller', 'Drama'],
                'rating': 8.9,
                'runtime': 135,
                'cert': 'U',
                'popularity': 840.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=70),
                'poster_url': 'https://image.tmdb.org/t/p/w500/bKxiLRPVWe2nZ9Pr6vmsQ3X8bHk.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/2KGxQFV9Wp1iCrPB6rV85qwR9pf.jpg',
                'desc': 'A group of close-knit friends embark on a road trip to Kodaikanal, turning into an unprecedented real-life rescue operation when one falls into Guna Caves.',
            },
            # Upcoming
            {
                'title': 'Kalki 2898 AD: The Complex Rising',
                'name': 'Kalki 2898 AD: The Complex Rising',
                'lang': 'te',
                'add_langs': ['hi', 'ta', 'kn', 'ml'],
                'genres': ['Sci-Fi', 'Epic'],
                'rating': 9.0,
                'runtime': 180,
                'cert': 'UA 13+',
                'popularity': 990.0,
                'status': 'UPCOMING',
                'release_date': datetime.date(2026, 5, 14),
                'poster_url': 'https://image.tmdb.org/t/p/w500/2KGxQFV9Wp1iCrPB6rV85qwR9pf.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/2KGxQFV9Wp1iCrPB6rV85qwR9pf.jpg',
                'desc': "The continuation of Ashwatthama and Bhairava's conflict inside the Supreme Yaskin's inverted pyramid sanctum.",
            },
            {
                'title': 'Gladiator II',
                'name': 'Gladiator II',
                'lang': 'en',
                'add_langs': ['hi'],
                'genres': ['Action', 'Epic'],
                'rating': 8.8,
                'runtime': 148,
                'cert': 'A',
                'popularity': 970.0,
                'status': 'UPCOMING',
                'release_date': datetime.date(2026, 6, 17),
                'poster_url': 'https://image.tmdb.org/t/p/w500/h3jLam0blH2pf5G5Qba2vsJt5eG.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/h3jLam0blH2pf5G5Qba2vsJt5eG.jpg',
                'desc': 'Lucius enters the Colosseum after his home is conquered by the tyrannical emperors who now lead Rome with iron fists.',
            },
            {
                'title': 'Game Changer',
                'name': 'Game Changer',
                'lang': 'te',
                'add_langs': ['ta', 'hi'],
                'genres': ['Action', 'Thriller'],
                'rating': 8.5,
                'runtime': 165,
                'cert': 'UA 16+',
                'popularity': 940.0,
                'status': 'UPCOMING',
                'release_date': datetime.date(2026, 7, 18),
                'poster_url': 'https://image.tmdb.org/t/p/w500/87W6wN5T9fE7s4A5JkL2e9G2k4A.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/87W6wN5T9fE7s4A5JkL2e9G2k4A.jpg',
                'desc': 'An honest and just IPS officer wages war against corrupt politicians during high-stakes state legislative polling.',
            },
            # Curated Classics
            {
                'title': 'K.G.F: Chapter 2',
                'name': 'K.G.F: Chapter 2',
                'lang': 'kn',
                'add_langs': ['hi', 'te', 'ta', 'ml'],
                'genres': ['Action', 'Crime'],
                'rating': 9.2,
                'runtime': 168,
                'cert': 'UA 16+',
                'popularity': 960.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=100),
                'poster_url': 'https://image.tmdb.org/t/p/w500/khkVzHjU2f4G3J6yvY8nF6v8eB0.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/khkVzHjU2f4G3J6yvY8nF6v8eB0.jpg',
                'desc': 'Rocky rules the blood-soaked gold mines of Narachi while Adheera, Ramika Sen, and the Indian armed forces close in on his reign.',
            },
            {
                'title': '777 Charlie',
                'name': '777 Charlie',
                'lang': 'kn',
                'add_langs': ['ta', 'te', 'ml', 'hi'],
                'genres': ['Adventure', 'Drama'],
                'rating': 8.9,
                'runtime': 164,
                'cert': 'U',
                'popularity': 920.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=120),
                'poster_url': 'https://image.tmdb.org/t/p/w500/8gP1fWzU7rQk6F8a9J3H9Q2F7d1.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/8gP1fWzU7rQk6F8a9J3H9Q2F7d1.jpg',
                'desc': 'Dharma, a lonely and bitter factory worker whose life is stuck in a monotonous cycle, finds purpose when an abandoned Labrador pup Charlie enters his world.',
            },
            {
                'title': 'GGVV',
                'name': 'GGVV',
                'lang': 'kn',
                'add_langs': [],
                'genres': ['Crime', 'Drama'],
                'rating': 8.7,
                'runtime': 151,
                'cert': 'A',
                'popularity': 900.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=150),
                'poster_url': 'https://image.tmdb.org/t/p/w500/2L2iQvE4v6w8K6a9j4h0d2b4a6r.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/2L2iQvE4v6w8K6a9j4h0d2b4a6r.jpg',
                'desc': 'In the coastal alleys of Mangaladevi, two fiercely loyal friends Shiva and Hari rise as undisputed mob powers until ego and dread collide.',
            },
            {
                'title': 'Dia (Anniversary Edition)',
                'name': 'Dia (Anniversary Edition)',
                'lang': 'kn',
                'add_langs': [],
                'genres': ['Romance', 'Drama'],
                'rating': 8.8,
                'runtime': 137,
                'cert': 'U',
                'popularity': 890.0,
                'status': 'CURRENT',
                'release_date': today - datetime.timedelta(days=180),
                'poster_url': 'https://image.tmdb.org/t/p/w500/6y5K803E1g1GqXyv5WvC5P1mS5W.jpg',
                'backdrop_url': 'https://image.tmdb.org/t/p/original/6y5K803E1g1GqXyv5WvC5P1mS5W.jpg',
                'desc': 'An introverted young biotech student navigates tragedy, heartbreak, and redemption in an intensely emotional rollercoaster.',
            },
        ]

        for mdata in movies_spec:
            m = Movie.objects.filter(title__icontains=mdata['name']).first()
            if not m:
                m = Movie.objects.filter(name__icontains=mdata['name']).first()
            if not m:
                m = Movie.objects.create(name=mdata['name'])

            m.title = mdata['title']
            m.name = mdata['name']
            m.original_language = mdata['lang']
            m.rating = mdata['rating']
            m.runtime = mdata['runtime']
            m.age_certification = mdata['cert']
            m.popularity = mdata['popularity']
            m.status = mdata['status']
            m.release_date = mdata['release_date']
            m.poster_url = mdata['poster_url']
            m.backdrop_url = mdata['backdrop_url']
            m.description = mdata['desc']
            m.trailer_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
            m.save()

            m.languages.clear()
            if mdata['lang'] in languages:
                m.languages.add(languages[mdata['lang']])
            for lcode in mdata.get('add_langs', []):
                if lcode in languages:
                    m.languages.add(languages[lcode])

            m.genres.clear()
            for gname in mdata.get('genres', []):
                if gname in genres:
                    m.genres.add(genres[gname])

            # If current movie, ensure at least one active future showtime in Galleria / Vega City
            if m.status == 'CURRENT' and created_screens:
                for scr in created_screens[:3]:
                    th, _ = Theater.objects.get_or_create(
                        movie=m,
                        screen=scr,
                        name=scr.theater_name,
                        city='Bengaluru',
                        time=future_showtime,
                        defaults={
                            'location': 'Bengaluru, Karnataka',
                            'latitude': 13.1007,
                            'longitude': 77.5963,
                            'active': True,
                            'price': 350.00,
                        }
                    )
                    th.active = True
                    th.time = future_showtime
                    th.save()

                    if th.seats.count() < 20:
                        Seat.objects.filter(theater=th).delete()
                        for r_char in ['A', 'B', 'C', 'D']:
                            for num in range(1, 11):
                                Seat.objects.create(
                                    theater=th,
                                    screen=scr,
                                    row=r_char,
                                    seat_number=f"{r_char}{num}",
                                    seat_type='VIP' if r_char in ['A', 'B'] else 'REGULAR',
                                    is_booked=False
                                )

        self.stdout.write(self.style.SUCCESS("Mockup cinema showcase data successfully populated!"))
