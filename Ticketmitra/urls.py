

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from movies import admin_views
from movies import views as movie_views

# Configure TicketMitra Operations Admin Branding
admin.site.site_header = "TicketMitra Operations"
admin.site.site_title = "TicketMitra Cinema Operations"
admin.site.index_title = "TicketMitra Operations Center"

# Connect Dashboard Statistics into Django Admin Index
_orig_admin_index = admin.site.index

def ticketmitra_admin_index(request, extra_context=None):
    extra = extra_context or {}
    try:
        stats = admin_views.dashboard_stats_context()
        extra.update(stats)
    except Exception:
        pass
    return _orig_admin_index(request, extra_context=extra)

admin.site.index = ticketmitra_admin_index

urlpatterns = [
    # TicketMitra Operations Admin Panel Routes
    path('admin/login/', admin_views.admin_login_view, name='admin_login'),
    path('admin/logout/', admin_views.admin_logout_view, name='admin_logout'),
    path('admin/dashboard/', admin_views.admin_dashboard_view, name='admin_dashboard'),
    path('admin/movies/', admin_views.admin_movies_view, name='admin_movies'),
    path('admin/theatres/', admin_views.admin_theatres_view, name='admin_theatres'),
    path('admin/screens/', admin_views.admin_screens_view, name='admin_screens'),
    path('admin/seats/', admin_views.visual_seat_map_view, name='admin_seats'),
    path('admin/pricing/', admin_views.admin_pricing_view, name='admin_pricing'),
    path('admin/showtimes/', admin_views.admin_showtimes_view, name='admin_showtimes'),
    path('admin/bookings/', admin_views.admin_bookings_view, name='admin_bookings'),
    path('admin/reservations/', admin_views.admin_reservations_view, name='admin_reservations'),
    path('admin/payments/', admin_views.admin_payments_view, name='admin_payments'),
    path('admin/users/', admin_views.admin_users_view, name='admin_users'),
    path('admin/reviews/', admin_views.admin_reviews_view, name='admin_reviews'),
    path('admin/reports/', admin_views.admin_reports_view, name='admin_reports'),
    path('admin/activity/', admin_views.admin_activity_view, name='admin_activity'),

    # Custom Cinema Operations Admin URLs (Staff protected)
    path('admin/operations/theater/<int:theater_id>/', admin_views.theater_detail_view, name='admin_theater_detail'),
    path('admin/operations/screen/<int:screen_id>/', admin_views.screen_detail_view, name='admin_screen_detail'),
    path('admin/operations/manage-seats/<int:theater_id>/', admin_views.visual_seat_map_view, name='admin_manage_seats_theater'),
    path('admin/operations/manage-seats/screen/<int:screen_id>/', admin_views.visual_seat_map_view, name='admin_manage_seats_screen'),
    path('admin/operations/manage-seats/', admin_views.visual_seat_map_view, name='admin_manage_seats_default'),
    path('admin/operations/seats/bulk-add/', admin_views.bulk_add_seats_view, name='admin_bulk_add_seats'),
    path('admin/operations/seats/action/', admin_views.seat_action_api, name='admin_seat_action'),
    path('admin/operations/analytics/', admin_views.analytics_view, name='admin_analytics'),
    path('admin/operations/analytics/export/', admin_views.export_analytics_csv, name='admin_analytics_export'),
    path('admin/operations/search/', admin_views.global_search_view, name='admin_global_search'),
    path('admin/operations/quick-booking/', admin_views.quick_booking_view, name='admin_quick_booking'),

    # Exact match for /admin/ -> Operations Dashboard
    path('admin/', admin_views.admin_dashboard_view, name='admin_root'),

    # Standard Django Admin fallback
    path('admin/sys/', admin.site.urls),
    path('api/create-order', movie_views.api_create_order, name='root_api_create_order'),
    path('api/verify-payment', movie_views.api_verify_payment, name='root_api_verify_payment'),
    path('', include('users.urls')),
    path('users/', include('users.urls')),
    path('movies/', include('movies.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
