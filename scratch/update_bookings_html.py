with open('Ticketmitra/templates/admin/bookings_list.html', 'r', encoding='utf-8') as f:
    c = f.read()

target = """                      {% if b.status == 'CONFIRMED' %}
                        <form method="POST" action="/admin/bookings/" onsubmit="return confirm('Cancel booking #{{ b.id }} and release seat {{ b.seat.seat_number }}?');" style="margin: 0; display: inline;">
                          {% csrf_token %}
                          <input type="hidden" name="action" value="cancel_booking">
                          <input type="hidden" name="booking_id" value="{{ b.id }}">
                          <button type="submit" class="tm-btn tm-btn-danger py-1 px-2 small" title="Cancel Booking">
                            <i class="fas fa-ban"></i>
                          </button>
                        </form>
                      {% endif %}"""

replacement = """                      {% if b.status == 'CONFIRMED' %}
                        <form method="POST" action="/admin/bookings/" onsubmit="return confirm('Cancel booking #{{ b.id }} and refund ₹{{ b.amount|default:b.ticket_price }} to customer?');" style="margin: 0; display: inline;">
                          {% csrf_token %}
                          <input type="hidden" name="action" value="cancel_booking">
                          <input type="hidden" name="booking_id" value="{{ b.id }}">
                          <input type="hidden" name="process_refund" value="1">
                          <input type="hidden" name="refund_reason" value="Staff initiated cancellation and refund">
                          <button type="submit" class="tm-btn tm-btn-danger py-1 px-2 small" title="Cancel & Refund">
                            <i class="fas fa-undo-alt mr-1"></i> Refund
                          </button>
                        </form>
                      {% endif %}"""

if target in c:
    c = c.replace(target, replacement, 1)
    with open('Ticketmitra/templates/admin/bookings_list.html', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Updated bookings_list.html successfully")
else:
    print("Target not found in bookings_list.html")

