import stripe
import secrets
import os
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, jsonify, current_app, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key
from config import get_stripe_config, get_chairfbi_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    cfg = get_stripe_config()
    stripe.api_key = cfg["secret_key"]

    product_name = f"BEAZT Cheats - {tier.product.name} ({tier.label})"
    product_desc = f"{tier.duration_days} day(s) access"

    if tier.is_subscription:
        product_name = f"BEAZT Private - {tier.product.name} ({tier.label})"
        product_desc = f"Billed once — {tier.duration_days} day(s) access"

    try:
        line_item = {
            "price_data": {
                "currency": "gbp",
                "product_data": {
                    "name": product_name,
                    "description": product_desc,
                },
                "unit_amount": tier.price_pence,
            },
            "quantity": 1,
        }

        if tier.is_subscription:
            line_item["price_data"]["recurring"] = {
                "interval": "day",
                "interval_count": tier.duration_days,
            }

        session_kwargs = {
            "customer_email": current_user.email,
            "client_reference_id": str(current_user.id),
            "line_items": [line_item],
            "metadata": {
                "user_id": str(current_user.id),
                "tier_id": str(tier.id),
                "duration_days": str(tier.duration_days),
                "product_id": str(tier.product_id),
                "product_slug": tier.product.slug,
                "is_subscription": str(tier.is_subscription).lower(),
            },
            "success_url": url_for("main.my_keys", _external=True),
            "cancel_url": url_for("main.product_detail", slug=tier.product.slug, _external=True),
        }

        if tier.is_subscription:
            session_kwargs["mode"] = "subscription"
        else:
            session_kwargs["mode"] = "payment"

        pmd = cfg.get("payment_method_domain", "")
        if pmd:
            session_kwargs["payment_method_configuration"] = pmd
        else:
            session_kwargs["payment_method_types"] = ["card"]

        session = stripe.checkout.Session.create(**session_kwargs)

        order = Order(
            user_id=current_user.id,
            tier_id=tier.id,
            stripe_session_id=session.id,
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        return redirect(session.url, code=303)
    except stripe.error.StripeError as e:
        logger.error("Stripe session creation failed: %s", e)
        return jsonify({"error": str(e)}), 500


@checkout_bp.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")
    cfg = get_stripe_config()
    endpoint_secret = cfg["webhook_secret"]

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        handle_checkout_completed(event["data"]["object"])
    elif event_type == "invoice.paid":
        handle_invoice_paid(event["data"]["object"])
    elif event_type == "customer.subscription.deleted":
        handle_subscription_deleted(event["data"]["object"])

    return jsonify({"status": "ok"})


def handle_checkout_completed(session_data):
    stripe_session_id = session_data.get("id")
    mode = session_data.get("mode", "payment")
    subscription_id = session_data.get("subscription")

    order = Order.query.filter_by(stripe_session_id=stripe_session_id).first()
    if not order:
        logger.warning("No order found for session: %s", stripe_session_id)
        return

    if order.status == "completed":
        return

    metadata = session_data.get("metadata", {})
    duration_days = int(metadata.get("duration_days", 30))
    product_id = int(metadata.get("product_id", order.tier.product_id if order.tier else 1))
    tier_id = int(metadata.get("tier_id", order.tier_id if order.tier_id else 0))
    is_subscription = metadata.get("is_subscription", "false") == "true"
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    from models import Product
    product = db.session.get(Product, product_id)
    key_source = product.key_source if product else "chairfbi"

    if subscription_id:
        order.stripe_subscription_id = subscription_id
        try:
            stripe.Subscription.modify(
                subscription_id,
                cancel_at=int((datetime.utcnow() + timedelta(days=duration_days)).timestamp()),
            )
        except stripe.error.StripeError:
            pass

    key_value = ""
    chairfbi_key_id = None
    chairfbi_cheat_id = None

    # 1) Try pool key first
    pool_key = (
        Key.query
        .filter_by(product_id=product_id, tier_id=tier_id, user_id=None, is_active=False)
        .order_by(Key.created_at.asc())
        .first()
    )
    if pool_key:
        pool_key.user_id = order.user_id
        pool_key.order_id = order.id
        pool_key.tier_id = tier_id
        pool_key.expires_at = expires_at
        pool_key.assigned_at = datetime.utcnow()
        pool_key.is_active = True
        pool_key.is_subscription = is_subscription
        order.status = "completed"
        db.session.commit()
        logger.info("Pool key assigned for order %s (subscription=%s)", order.id, is_subscription)
        return

    # 2) Pool-only product with empty pool — auto-generate key
    if key_source == "pool":
        logger.info("Pool depleted for product %s — auto-generating key for order %s",
                   product.name if product else "unknown", order.id)

    # 3) ChairFBI product — generate key via API
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    cheat_id = ""

    if order.tier and order.tier.product and order.tier.product.chairfbi_cheat_id:
        cheat_id = order.tier.product.chairfbi_cheat_id

    if cheat_id and api_token:
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=api_token, base_url=cfg.get("api_base"))
            result = cf.create_key(cheat_id=cheat_id, days=duration_days)
            keys = result.get("keys", [])
            key_value = keys[0] if keys else ""
            chairfbi_key_id = key_value
            chairfbi_cheat_id = cheat_id
        except Exception:
            logger.exception("ChairFBI key creation failed for order %s", order.id)

    if not key_value:
        key_value = "BEAZT-" + secrets.token_hex(16).upper()

    order.status = "completed"

    key = Key(
        user_id=order.user_id,
        order_id=order.id,
        product_id=product_id,
        tier_id=tier_id,
        key_value=key_value,
        expires_at=expires_at,
        is_subscription=is_subscription,
        chairfbi_key_id=chairfbi_key_id,
        chairfbi_cheat_id=chairfbi_cheat_id,
    )
    db.session.add(key)
    db.session.commit()
    logger.info("Key created for order %s (subscription=%s)", order.id, is_subscription)


def handle_invoice_paid(invoice):
    """Handle recurring subscription payment — extend key expiry."""
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return

    billing_reason = invoice.get("billing_reason", "")
    if billing_reason == "subscription_create":
        return

    order = Order.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not order:
        logger.warning("No order found for subscription: %s", subscription_id)
        return

    key = Key.query.filter_by(order_id=order.id).first()
    if not key:
        logger.warning("No key found for order: %s", order.id)
        return

    tier = order.tier
    if not tier:
        return

    key.is_active = True
    key.expires_at = datetime.utcnow() + timedelta(days=tier.duration_days)
    db.session.commit()
    logger.info("Subscription renewed for order %s — key extended to %s", order.id, key.expires_at)


def handle_subscription_deleted(subscription):
    """Handle subscription cancellation — expire the key."""
    subscription_id = subscription.get("id")
    if not subscription_id:
        return

    order = Order.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not order:
        logger.warning("No order found for deleted subscription: %s", subscription_id)
        return

    key = Key.query.filter_by(order_id=order.id).first()
    if key:
        key.is_active = False
        logger.info("Key expired for subscription cancellation — order %s", order.id)

    order.status = "cancelled"
    db.session.commit()
