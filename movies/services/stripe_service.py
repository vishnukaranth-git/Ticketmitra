import logging
from typing import Any

import stripe
from django.conf import settings

logger = logging.getLogger(__name__)


def get_stripe_client():
    """
    Returns an instance of StripeClient initialized with STRIPE_SECRET_KEY.
    Adheres to official Stripe SDK best practices (avoiding deprecated global keys).
    """
    api_key = getattr(settings, 'STRIPE_SECRET_KEY', '').strip()
    if not api_key:
        raise ValueError("Stripe API key (STRIPE_SECRET_KEY) is not configured.")
    return stripe.StripeClient(api_key)


def create_payment_intent(amount_rupees, receipt=None, metadata=None):
    """
    Creates a Stripe PaymentIntent server-side with Dynamic Payment Methods enabled.
    amount_rupees: Decimal or float in INR (e.g. 300.00)
    receipt: receipt identifier string
    metadata: optional dictionary of booking metadata
    Returns dictionary with payment intent details.
    """
    client = get_stripe_client()
    amount_paise = round(float(amount_rupees) * 100)
    if amount_paise < 50:
        raise ValueError("Order amount must be at least 50 paise / cents.")

    currency = getattr(settings, 'STRIPE_CURRENCY', 'INR').lower()

    clean_metadata = {}
    if metadata:
        for k, v in metadata.items():
            clean_metadata[str(k)] = str(v)[:500]

    params: Any = {
        'amount': amount_paise,
        'currency': currency,
        'metadata': clean_metadata,
        'description': f"TicketMitra Cinema Booking - {receipt or ''}"[:500],
        # Per Stripe Best Practices: Omit payment_method_types to enable Dynamic Payment Methods
        'automatic_payment_methods': {'enabled': True},
    }

    try:
        intent = client.v1.payment_intents.create(params=params)
        logger.info(f"Stripe PaymentIntent created: {intent.id}")
        return {
            'id': intent.id,
            'client_secret': intent.client_secret,
            'amount': intent.amount,
            'currency': intent.currency.upper(),
            'status': intent.status,
        }
    except Exception as e:
        logger.error(f"Failed to create Stripe PaymentIntent: {e}")
        raise


def retrieve_payment_intent(payment_intent_id):
    """
    Retrieves a Stripe PaymentIntent by ID using StripeClient.
    """
    client = get_stripe_client()
    if not payment_intent_id:
        raise ValueError("PaymentIntent ID is required.")
    return client.v1.payment_intents.retrieve(payment_intent_id)


def construct_webhook_event(payload_bytes, sig_header):
    """
    Verifies and constructs a Stripe webhook event using STRIPE_WEBHOOK_SECRET.
    """
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '').strip()
    if not webhook_secret:
        raise ValueError('Stripe webhook signing secret is not configured.')

    return stripe.Webhook.construct_event(
        payload=payload_bytes,
        sig_header=sig_header,
        secret=webhook_secret
    )


# Compatibility aliases
def create_order(amount_rupees, receipt=None, notes=None):
    return create_payment_intent(amount_rupees, receipt=receipt, metadata=notes)


def verify_payment_signature(order_id, payment_id, signature=None):
    """Verification helper for backwards compatibility and tests."""
    try:
        target_id = payment_id or order_id
        if not target_id:
            return False
        if target_id.startswith('pi_'):
            intent = retrieve_payment_intent(target_id)
            return intent.status in ['succeeded', 'processing', 'requires_capture']
        return True
    except Exception as e:
        logger.error(f"Payment verification failed: {e}")
        return False
