with open('Ticketmitra/movies/admin_views.py', 'r', encoding='utf-8') as f:
    av = f.read()

# 1. slot_time try-except
av = av.replace("""                    try:
                        slot_time = datetime.strptime(slot_str, '%H:%M').time()
                        show_dt = timezone.make_aware(datetime.combine(cur_date, slot_time))
                    except Exception:
                        continue""",
"""                    try:
                        slot_time = datetime.strptime(slot_str, '%H:%M').time()
                        show_dt = timezone.make_aware(datetime.combine(cur_date, slot_time))
                    except (ValueError, TypeError) as exc:
                        logger.debug(f"Skipping invalid slot '{slot_str}': {exc}")
                        continue""")

# 2. refund_done
av = av.replace("""            refund_done = False
            if process_refund:
                booking.cancel(refund=True)
                booking.refund_amount = booking.amount
                booking.save(update_fields=['status', 'cancelled_at', 'refund_amount'])

                # Find associated payment
                payment = Payment.objects.filter(Q(booking=booking) | Q(bookings=booking)).first()
                if payment and payment.status != 'REFUNDED':
                    payment.status = 'REFUNDED'
                    payment.failure_reason = f"Refunded: {reason}"
                    payment.save(update_fields=['status', 'failure_reason'])
                    refund_done = True""",
"""            if process_refund:
                booking.cancel(refund=True)
                booking.refund_amount = booking.amount
                booking.save(update_fields=['status', 'cancelled_at', 'refund_amount'])

                # Find associated payment
                payment = Payment.objects.filter(Q(booking=booking) | Q(bookings=booking)).first()
                if payment and payment.status != 'REFUNDED':
                    payment.status = 'REFUNDED'
                    payment.failure_reason = f"Refunded: {reason}"
                    payment.save(update_fields=['status', 'failure_reason'])""")

# 3. stripe_err
av = av.replace("except Exception as stripe_err:", "except Exception:")

with open('Ticketmitra/movies/admin_views.py', 'w', encoding='utf-8') as f:
    f.write(av)

with open('Ticketmitra/movies/views.py', 'r', encoding='utf-8') as f:
    v = f.read()

# 4. Remove unused PricingPlan import from views.py
v = v.replace("    PricingPlan,\n", "")

with open('Ticketmitra/movies/views.py', 'w', encoding='utf-8') as f:
    f.write(v)

print("Fixed lint issues successfully")

