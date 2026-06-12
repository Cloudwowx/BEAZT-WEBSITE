import secrets
import logging
from datetime import datetime, timedelta

import requests
from flask import Blueprint, request, redirect, jsonify, url_for
from flask_login import current_user, login_required
from models import db, User, PricingTier, Order, Key
from config import get_shoppy_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

SHOPPY_API = "https://shoppy.gg/api/v2"


def _shoppy_headers():
    cfg = get_shoppy_config()
    return {"Authorization": cfg["api_key"]}


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    cfg = get_shoppy_config()
    if not cfg["api_key"]:
        return jsonify({"error": "Shoppy API key not configured"}), 500

    try:
        payload = {
            "title": f"BEAZT License - {tier.product.name} ({tier.label})",
            "value": tier.price_pounds,
            "email": current_user.email,
            "webhook_urls": [url_for("checkout.webhook", _external=True)],
            "custom_fields": [
                {"name": "user_id", "type": "number", "value": str(current_user.id)},
                {"name": "tier_id", "type": "number", "value": str(tier.id)},
                {"name": "product_id", "type": "number", "value": str(tier.product_id)},
                {"name": "duration_days", "type": "number", "value": str(tier.duration_days)},
                {"name": "is_subscription", "type": "text", "value": str(tier.is_subscription).lower()},
            ],
        }

        resp = requests.post(
            f"{SHOPPY_API}/pay",
            json=payload,
            headers=_shoppy_headers(),
            timeout=15,
        )
        data = resp.json()

        if not data.get("status"):
            msg = data.get("error") or data.get("message") or f"HTTP {resp.status_code}"
            logger.error("Shoppy pay creation failed: %s", msg)
            return jsonify({"error": str(msg)}), 500

        payment_url = data.get("url")
        if not payment_url:
            return jsonify({"error": "No checkout URL returned"}), 500

        order = Order(
            user_id=current_user.id,
            tier_id=tier.id,
            stripe_session_id=str(data.get("id", "")),
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        return redirect(payment_url, code=303)

    except Exception as e:
        logger.exception("Shoppy checkout failed")
        return jsonify({"error": str(e)}), 500


@checkout_bp.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error"}), 400

    event = payload.get("event", "")
    data = payload.get("data", {})
    logger.info("Shoppy webhook: %s", event)

    if event in ("order.completed", "order.paid", "charge.completed"):
        _handle_order(data)

    return jsonify({"status": "ok"})


def _handle_order(data):
    fields = {}
    for f in data.get("custom_fields", []):
        fields[f["name"]] = f.get("value", "")

    email = data.get("email", "")

    user_id = int(fields.get("user_id", 0))
    tier_id = int(fields.get("tier_id", 0))
    product_id = int(fields.get("product_id", 1))
    duration_days = int(fields.get("duration_days", 30))
    is_subscription = fields.get("is_subscription", "false") == "true"

    user = db.session.get(User, user_id) if user_id else User.query.filter_by(email=email).first()
    if not user:
        logger.warning("No user found for Shoppy order: %s", email)
        return

    tier = db.session.get(PricingTier, tier_id) if tier_id else None
    if not tier:
        logger.warning("No tier found for Shoppy order")
        return

    order = Order.query.filter_by(
        user_id=user.id, tier_id=tier.id, status="pending"
    ).order_by(Order.created_at.desc()).first()

    if order and order.status == "completed":
        return

    if not order:
        order = Order(
            user_id=user.id,
            tier_id=tier.id,
            stripe_session_id=data.get("id", ""),
            status="completed",
        )
        db.session.add(order)
        db.session.flush()

    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    pool_key = (
        Key.query
        .filter_by(product_id=product_id, tier_id=tier_id, user_id=None, is_active=False)
        .order_by(Key.created_at.asc())
        .first()
    )
    if pool_key:
        pool_key.user_id = user.id
        pool_key.order_id = order.id
        pool_key.tier_id = tier.id
        pool_key.expires_at = expires_at
        pool_key.assigned_at = datetime.utcnow()
        pool_key.is_active = True
        pool_key.is_subscription = is_subscription
        order.status = "completed"
        db.session.commit()
        logger.info("Pool key assigned for Shoppy order %s", order.id)
        return

    key_value = "BEAZT-" + secrets.token_hex(16).upper()
    order.status = "completed"
    key = Key(
        user_id=user.id,
        order_id=order.id,
        product_id=product_id,
        tier_id=tier_id,
        key_value=key_value,
        expires_at=expires_at,
        is_subscription=is_subscription,
    )
    db.session.add(key)
    db.session.commit()
    logger.info("Key auto-generated for Shoppy order %s", order.id)
