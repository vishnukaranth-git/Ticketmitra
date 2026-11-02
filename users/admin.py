from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html

# Unregister default UserAdmin
admin.site.unregister(User)


@admin.register(User)
class TicketMitraUserAdmin(BaseUserAdmin):
    list_display = (
        'user_avatar', 'username', 'get_full_name', 'email',
        'bookings_count', 'payments_count', 'is_staff_badge', 'is_active_badge', 'date_joined_formatted'
    )
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'date_joined')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('-date_joined',)

    @admin.display(description="")
    def user_avatar(self, obj):
        initial = (obj.username[0] if obj.username else 'U').upper()
        bg = "#E63946" if obj.is_superuser else ("#3B82F6" if obj.is_staff else "#64748b")
        return format_html(
            '<div style="width: 32px; height: 32px; border-radius: 50%; background: {}; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">{}</div>',
            bg, initial
        )

    @admin.display(description="Bookings")
    def bookings_count(self, obj):
        count = obj.booking_set.count()
        if count > 0:
            url = reverse('admin:movies_booking_changelist') + f"?user__id__exact={obj.id}"
            return format_html('<a href="{}" class="tm-badge tm-badge-blue">{} Bookings</a>', url, count)
        return "0"

    @admin.display(description="Payments")
    def payments_count(self, obj):
        count = obj.payments.count()
        if count > 0:
            url = reverse('admin:movies_payment_changelist') + f"?user__id__exact={obj.id}"
            return format_html('<a href="{}" class="tm-badge tm-badge-success">{} Paid</a>', url, count)
        return "0"

    @admin.display(description="Staff / Role")
    def is_staff_badge(self, obj):
        if obj.is_superuser:
            return format_html('<span class="tm-badge tm-badge-danger">Superuser</span>')
        if obj.is_staff:
            return format_html('<span class="tm-badge tm-badge-warning">Staff</span>')
        return format_html('<span class="tm-badge tm-badge-muted">Customer</span>')

    @admin.display(description="Status")
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="tm-badge tm-badge-success">Active</span>')
        return format_html('<span class="tm-badge tm-badge-danger">Inactive</span>')

    @admin.display(description="Joined")
    def date_joined_formatted(self, obj):
        return obj.date_joined.strftime('%b %d, %Y')
