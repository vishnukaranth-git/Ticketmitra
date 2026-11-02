import logging
import math

from django.db.models import Q
from django.utils import timezone

from movies.models import CinemaVenue, Movie, SeatReservation, Theater

logger = logging.getLogger(__name__)

# Standard coordinates for major Indian cinema hub cities (for fallback & distance reference)
CITY_CENTROIDS = {
    'bengaluru': {'name': 'Bengaluru', 'lat': 12.9716, 'lon': 77.5946, 'state': 'Karnataka'},
    'bangalore': {'name': 'Bengaluru', 'lat': 12.9716, 'lon': 77.5946, 'state': 'Karnataka'},
    'chennai': {'name': 'Chennai', 'lat': 13.0827, 'lon': 80.2707, 'state': 'Tamil Nadu'},
    'hyderabad': {'name': 'Hyderabad', 'lat': 17.3850, 'lon': 78.4867, 'state': 'Telangana'},
    'mumbai': {'name': 'Mumbai', 'lat': 19.0760, 'lon': 72.8777, 'state': 'Maharashtra'},
    'delhi': {'name': 'Delhi', 'lat': 28.6139, 'lon': 77.2090, 'state': 'Delhi NCR'},
    'kochi': {'name': 'Kochi', 'lat': 9.9312, 'lon': 76.2673, 'state': 'Kerala'},
    'mysuru': {'name': 'Mysuru', 'lat': 12.2958, 'lon': 76.6394, 'state': 'Karnataka'},
    'mysore': {'name': 'Mysuru', 'lat': 12.2958, 'lon': 76.6394, 'state': 'Karnataka'},
    'pune': {'name': 'Pune', 'lat': 18.5204, 'lon': 73.8567, 'state': 'Maharashtra'},
    'kolkata': {'name': 'Kolkata', 'lat': 22.5726, 'lon': 88.3639, 'state': 'West Bengal'},
}

SUPPORTED_CITIES = [
    'Bengaluru', 'Chennai', 'Hyderabad', 'Mumbai',
    'Delhi', 'Kochi', 'Mysuru', 'Pune', 'Kolkata'
]


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Computes exact great-circle distance between two geographic coordinates in kilometers.
    Uses spherical Earth radius R = 6371.0 km.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    try:
        lat1, lon1 = float(lat1), float(lon1)
        lat2, lon2 = float(lat2), float(lon2)
    except (ValueError, TypeError):
        return None

    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 2)


def find_nearest_city_name(lat, lon):
    """Finds closest known metropolitan city for coordinates."""
    closest_city = 'Bengaluru'
    min_dist = float('inf')
    for cdata in CITY_CENTROIDS.values():
        d = haversine_distance(lat, lon, cdata['lat'], cdata['lon'])
        if d is not None and d < min_dist:
            min_dist = d
            closest_city = cdata['name']
    return closest_city


def get_user_location_from_request(request):
    """
    Extracts user location from session or query parameters.
    Default radius: 30 km.
    """
    session_loc = request.session.get('user_location') or {}

    # Check query overrides
    lat = request.GET.get('lat')
    lng = request.GET.get('lng') or request.GET.get('lon')
    city = request.GET.get('city')
    radius = request.GET.get('radius')

    try:
        radius = float(radius) if radius else float(session_loc.get('radius', 30.0))
    except (ValueError, TypeError):
        radius = 30.0

    if lat and lng:
        try:
            lat = float(lat)
            lng = float(lng)
            city = city or find_nearest_city_name(lat, lng)
            user_loc = {
                'lat': lat,
                'lng': lng,
                'city': city,
                'radius': radius,
                'method': 'geolocation',
                'is_detected': True,
            }
            request.session['user_location'] = user_loc
            return user_loc
        except (ValueError, TypeError):
            pass

    if city:
        city_clean = city.strip()
        matched = CITY_CENTROIDS.get(city_clean.lower())
        lat = matched['lat'] if matched else None
        lng = matched['lon'] if matched else None
        user_loc = {
            'lat': lat,
            'lng': lng,
            'city': matched['name'] if matched else city_clean,
            'radius': radius,
            'method': 'city',
            'is_detected': False,
        }
        request.session['user_location'] = user_loc
        return user_loc

    if session_loc and (session_loc.get('lat') or session_loc.get('city')):
        session_loc['radius'] = radius
        if not session_loc.get('lng') and session_loc.get('lon'):
            session_loc['lng'] = session_loc.get('lon')
        if not session_loc.get('lon') and session_loc.get('lng'):
            session_loc['lon'] = session_loc.get('lng')
        return session_loc

    # Default fallback: Bengaluru (requires browser prompt or explicit selection)
    return {
        'lat': 13.0827,
        'lng': 77.5877,
        'lon': 77.5877,
        'city': 'Bengaluru',
        'radius': radius,
        'method': 'default',
        'is_detected': False,
    }


def get_nearby_theaters_and_movies(request, movie_id=None, language_code=None, include_city_directory=False):
    """
    Finds theaters within user's 30 km radius (Haversine formula) and their active screens/showtimes.
    Filters:
    - Distance <= 30 km
    - Theaters sorted by distance (nearest first)
    - Movies: status == 'CURRENT', release_date <= today, active upcoming showtimes
    - Language: matches regional language filter if provided
    """
    now = timezone.now()
    today = now.date()
    user_loc = get_user_location_from_request(request)
    u_lat = user_loc.get('lat')
    u_lng = user_loc.get('lng') or user_loc.get('lon')
    u_city = user_loc.get('city')
    radius_km = float(user_loc.get('radius', 30.0))

    # Base Query: active showtimes in the future
    showtimes_qs = Theater.objects.filter(
        active=True,
        time__gte=now,
        movie__status='CURRENT',
        movie__release_date__lte=today
    ).select_related('movie', 'screen')

    if movie_id:
        showtimes_qs = showtimes_qs.filter(movie_id=movie_id)

    if language_code:
        lang = language_code.strip().lower()
        showtimes_qs = showtimes_qs.filter(
            Q(movie__original_language=lang) | Q(movie__languages__code=lang)
        ).distinct()

    # Distinct venues
    venues = {}
    for st in showtimes_qs:
        v_name = st.name
        if v_name not in venues:
            st_lat = st.latitude
            st_lon = st.longitude
            if st_lat is None or st_lon is None:
                venue_obj = CinemaVenue.objects.filter(name=v_name).first()
                if venue_obj and venue_obj.latitude and venue_obj.longitude:
                    st_lat = venue_obj.latitude
                    st_lon = venue_obj.longitude

            dist = None
            if u_lat is not None and u_lng is not None and st_lat is not None and st_lon is not None:
                dist = haversine_distance(u_lat, u_lng, st_lat, st_lon)
            elif u_city and st.city and u_city.lower() == st.city.lower():
                # When only a city is selected, measure from its known centroid.
                centroid = CITY_CENTROIDS.get(u_city.lower())
                if centroid and st_lat is not None and st_lon is not None:
                    dist = haversine_distance(centroid['lat'], centroid['lon'], st_lat, st_lon)

            # Radius filtering: strictly <= radius_km (default 30 km)
            # If coordinates are known and dist > radius_km, exclude venue
            if dist is not None and dist > radius_km:
                continue

            # If user selected city only and venue is in a completely different city, exclude
            if (u_lat is None or user_loc.get('method') == 'city') and u_city and st.city and st.city.lower() != u_city.lower():
                continue

            venues[v_name] = {
                'name': v_name,
                'location': st.location,
                'address': st.address or st.location,
                'city': st.city,
                'state': st.state,
                'latitude': float(st.latitude) if st.latitude else None,
                'longitude': float(st.longitude) if st.longitude else None,
                'distance': dist,
                'distance_display': f"{dist} km away" if dist is not None else "Nearby",
                'screens': {},
                'showtimes_count': 0,
            }

        if v_name in venues:
            venue = venues[v_name]
            screen_key = st.screen.name if st.screen else "Main Screen"
            screen_type = st.screen.screen_type if st.screen else "Standard"

            if screen_key not in venue['screens']:
                venue['screens'][screen_key] = {
                    'name': screen_key,
                    'screen_type': screen_type,
                    'capacity': st.screen.capacity if st.screen else 30,
                    'screen_id': st.screen.id if st.screen else None,
                    'showtimes': [],
                }

            # Seat availability computation for this showtime
            total_seats = st.seats.count() or (st.screen.capacity if st.screen else 30)
            booked_count = st.seats.filter(is_booked=True).count()
            # Active unexpired reservations
            reserved_count = SeatReservation.objects.filter(
                theater=st,
                status='ACTIVE',
                expires_at__gt=now
            ).values('seats').distinct().count()
            blocked_count = st.seats.filter(is_blocked=True).count()
            available_count = max(0, total_seats - booked_count - reserved_count - blocked_count)

            venue['screens'][screen_key]['showtimes'].append({
                'theater_id': st.id,
                'movie': st.movie,
                'time': st.time,
                'time_formatted': st.time.strftime('%I:%M %p'),
                'date_formatted': st.time.strftime('%b %d'),
                'price': float(st.price),
                'available_seats': available_count,
                'reserved_seats': reserved_count,
                'booked_seats': booked_count,
                'blocked_seats': blocked_count,
                'total_seats': total_seats,
            })
            venue['showtimes_count'] += 1

    # Ensure real partner venues for the city are also represented (without assuming all have shows)
    if u_city:
        city_venues = CinemaVenue.objects.filter(city__iexact=u_city, active=True)
        for cv in city_venues:
            # Skip invalid test venue names
            if cv.name in ['faea', 'hjukuyku', 'rdj']:
                continue
            if cv.name not in venues:
                dist = None
                if u_lat is not None and u_lng is not None and cv.latitude is not None and cv.longitude is not None:
                    dist = haversine_distance(u_lat, u_lng, cv.latitude, cv.longitude)

                if dist is not None and dist > radius_km:
                    continue

                venues[cv.name] = {
                    'name': cv.name,
                    'location': cv.address or cv.city,
                    'address': cv.address or f"{cv.city}, {cv.state}",
                    'city': cv.city,
                    'state': cv.state,
                    'latitude': float(cv.latitude) if cv.latitude else None,
                    'longitude': float(cv.longitude) if cv.longitude else None,
                    'distance': dist,
                    'distance_display': f"{dist} km away" if dist is not None else None,
                    'screens': {},
                    'showtimes_count': 0,
                }

    # The all-theatres directory also includes real non-partner venues already
    # recorded on showtime rows, even when they have no current qualifying show.
    # Movie-specific selection pages remain limited to theatres for that movie.
    if u_city and include_city_directory and movie_id is None:
        directory_rows = Theater.objects.filter(
            city__iexact=u_city,
            latitude__isnull=False,
            longitude__isnull=False,
        ).exclude(name='').values(
            'name', 'location', 'address', 'city', 'state',
            'latitude', 'longitude',
        ).order_by('name')

        for row in directory_rows:
            venue_name = row['name']
            if venue_name in venues:
                continue

            venue_lat = float(row['latitude'])
            venue_lon = float(row['longitude'])
            dist = haversine_distance(u_lat, u_lng, venue_lat, venue_lon)
            if dist is not None and dist > radius_km:
                continue

            venues[venue_name] = {
                'name': venue_name,
                'location': row['location'],
                'address': row['address'] or row['location'] or row['city'],
                'city': row['city'],
                'state': row['state'],
                'latitude': venue_lat,
                'longitude': venue_lon,
                'distance': dist,
                'distance_display': f"{dist} km away" if dist is not None else None,
                'screens': {},
                'showtimes_count': 0,
            }

    # Convert venues dict to list and sort by distance ascending (None distances placed at end)
    theaters_list = list(venues.values())
    theaters_list.sort(key=lambda x: (
        x['distance'] is None,
        x['distance'] if x['distance'] is not None else float('inf'),
    ))

    # Convert screens dict inside each theater to list
    for t in theaters_list:
        t['screens_list'] = list(t['screens'].values())

    # Extract current movies actively screening in these nearby theaters
    active_movie_ids = set()
    for t in theaters_list:
        for sc in t['screens_list']:
            for st in sc['showtimes']:
                active_movie_ids.add(st['movie'].id)

    current_movies = list(
        Movie.objects.filter(
            id__in=active_movie_ids,
            status='CURRENT',
            release_date__lte=today
        ).prefetch_related('genres', 'languages').order_by('-popularity', '-release_date')
    )

    return {
        'theaters': theaters_list,
        'current_movies': current_movies,
        'user_location': user_loc,
        'radius_km': radius_km,
        'total_theaters': len(theaters_list),
        'supported_cities': SUPPORTED_CITIES,
    }
