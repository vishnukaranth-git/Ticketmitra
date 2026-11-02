from django.urls import path

from . import views

urlpatterns = [
    path('', views.movie_list, name='movie_list'),
    path('search/suggestions/', views.search_suggestions, name='search_suggestions'),
    path('<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('<int:movie_id>/trailer/preview/', views.movie_trailer_preview, name='movie_trailer_preview'),
    path('<int:movie_id>/trailer/update/', views.update_trailer, name='update_trailer'),
    path('theaters/', views.theater_list, name='all_theaters_list'),
    path('<int:movie_id>/theaters/', views.theater_list, name='theater_list'),
    path('<int:movie_id>/theaters', views.theater_list),
    path('<int:movie_id>/review/', views.add_review, name='add_review'),
    path('review/<int:review_id>/edit/', views.edit_review, name='edit_review'),
    path('review/<int:review_id>/delete/', views.delete_review, name='delete_review'),
    path('review/<int:review_id>/report/', views.report_review, name='report_review'),

    # Smart Seat Reservation & Booking Flow
    path('theater/<int:theater_id>/seats/book/', views.book_seats, name='book_seats'),
    path('theater/<int:theater_id>/seats/status/', views.seat_status, name='seat_status'),
    path('theater/<int:theater_id>/reserve/', views.reserve_seats, name='reserve_seats'),
    path('theater/<int:theater_id>/reservation/update/', views.update_reservation, name='update_reservation'),
    path('theater/<int:theater_id>/reservation/cancel/', views.cancel_reservation, name='cancel_reservation'),

    # Checkout & Payment Confirmation
    path('checkout/<int:reservation_id>/', views.checkout, name='checkout'),
    path('checkout/<int:reservation_id>/apply-coupon/', views.apply_coupon, name='apply_coupon'),
    path('checkout/<int:reservation_id>/create_order/', views.create_payment_order, name='create_payment_order'),
    path('checkout/<int:reservation_id>/verify/', views.verify_payment, name='verify_payment'),
    path('checkout/<int:reservation_id>/failure/', views.payment_failure, name='payment_failure'),
    path('checkout/<int:reservation_id>/confirm/', views.confirm_payment, name='confirm_payment'),

    # Stripe Webhook
    path('payment/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('payment/razorpay-webhook/', views.stripe_webhook, name='razorpay_webhook'),

    # Generic API Endpoints
    path('api/create-order', views.api_create_order, name='api_create_order'),
    path('api/verify-payment', views.api_verify_payment, name='api_verify_payment'),

    # Booking & Ticket Management
    path('bookings/<int:booking_id>/ticket/', views.booking_ticket, name='booking_ticket'),
    path('bookings/<int:booking_id>/download-ticket/', views.download_ticket_pdf, name='download_ticket_pdf'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('payments/', views.payment_history, name='payment_history'),

    # Location & 30km Theater Discovery APIs
    path('api/set-location/', views.set_location_api, name='set_location_api'),
    path('api/nearby-theaters/', views.nearby_theaters_api, name='nearby_theaters_api'),

    # Automated Weekly Friday Movies Discovery & Refresh APIs
    path('api/weekly-movies/', views.weekly_movies_api, name='api_weekly_movies'),
    path('api/weekly-movies/refresh/', views.trigger_weekly_sync_api, name='api_trigger_weekly_sync'),
]