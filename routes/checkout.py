import stripe
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, jsonify, current_app, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key
from config import get_stripe_config

checkout_bp = Blueprint("checkout", __name__)


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

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            customer_email=current_user.email,
            client_reference_id=str(current_user.id),
            line_items=[{
                "price_data": {
                    "currency": "gbp",
                    "product_data": {
                        "name": f"BeaZt Cheats - {tier.product.name} ({tier.label})",
                        "description": f"{tier.duration_days} day(s) access",
                    },
                    "unit_amount": tier.price_pence,
                },
                "quantity": 1,
            }],
            metadata={
                "user_id": str(current_user.id),
                "tier_id": str(tier.id),
                "duration_days": str(tier.duration_days),
                "product_id": str(tier.product_id),
            },
            success_url=url_for("main.my_keys", _external=True),
            cancel_url=url_for("main.product_detail", slug="rust-external-private", _external=True),
        )

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

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        handle_checkout_completed(session_data)

    return jsonify({"status": "ok"})


def handle_checkout_completed(session_data):
    stripe_session_id = session_data.get("id")
    order = Order.query.filter_by(stripe_session_id=stripe_session_id).first()
    if not order:
        return

    if order.status == "completed":
        return

    order.status = "completed"

    metadata = session_data.get("metadata", {})
    duration_days = int(metadata.get("duration_days", 30))
    product_id = int(metadata.get("product_id", 1))

    key_value = "BEAZT-" + secrets.token_hex(16).upper()
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    key = Key(
        user_id=order.user_id,
        order_id=order.id,
        product_id=product_id,
        key_value=key_value,
        expires_at=expires_at,
    )
    db.session.add(key)
    db.session.commit()
