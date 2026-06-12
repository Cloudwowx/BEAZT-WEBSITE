import secrets
import hashlib
import hmac
import logging
from datetime import datetime, timedelta

import requests
from flask import Blueprint, request, redirect, jsonify, url_for
from flask_login import current_user, login_required
from models import db, User, PricingTier, Order, Key
from config import get_sellapp_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

SELLAPP_API = "https://sell.app/api/v2"


def _sellapp_headers():
    cfg = get_sellapp_config()
    return {"Authorization": f"Bearer {cfg['api_key']}"}


def _reference_str(tier, user_id):
    return f"user:{user_id}|tier:{tier.id}|days:{tier.duration_days}|sub:{tier.is_subscription}"


def _parse_reference(reference):
    parts = {}
    if reference:
        for p in reference.split("|"):
            if ":" in p:
                k, v = p.split(":", 1)
                parts[k] = v
    return parts


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    cfg = get_sellapp_config()
    if not cfg["api_key"]:
        return jsonify({"error": "SellApp API key not configured"}), 500

    try:
        payload = {
            "email": current_user.email,
            "return_url": url_for("main.my_keys", _external=True),
            "total": tier.price_pence,
            "currency": "GBP",
            "webhook": url_for("checkout.webhook", _external=True),
            "reference": _reference_str(tier, current_user.id),
            "description": f"BEAZT License - {tier.product.name} ({tier.label})",
            "use_all_payment_methods": True,
            "metadata": {
                "user_id": str(current_user.id),
                "tier_id": str(tier.id),
                "product_id": str(tier.product_id),
                "duration_days": str(tier.duration_days),
                "is_subscription": str(tier.is_subscription).lower(),
            },
        }

        if tier.is_subscription:
            if tier.duration_days >= 28:
                payload["recurring"] = True
                payload["interval"] = "month"
                payload["interval_count"] = max(1, tier.duration_days // 30)
            else:
                payload["recurring"] = True
                payload["interval"] = "day"
                payload["interval_count"] = tier.duration_days

        resp = requests.post(
            f"{SELLAPP_API}/charges",
            json=payload,
            headers=_sellapp_headers(),
            timeout=15,
        )
        data = resp.json()

        if resp.status_code not in (200, 201):
            err = data.get("message") or data.get("error") or f"HTTP {resp.status_code}"
            logger.error("SellApp charge creation failed: %s", err)
            return jsonify({"error": str(err)}), 500

        charge_data = data.get("data", data)
        payment_url = charge_data.get("url")

        if not payment_url:
            return jsonify({"error": "No checkout URL returned"}), 500

        order = Order(
            user_id=current_user.id,
            tier_id=tier.id,
            stripe_session_id=str(charge_data.get("id", "")),
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        return redirect(payment_url, code=303)

    except Exception as e:
        logger.exception("SellApp checkout failed")
        return jsonify({"error": str(e)}), 500


@checkout_bp.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_data(as_text=True)
    cfg = get_sellapp_config()

    # Verify HMAC signature
    webhook_secret = cfg.get("webhook_secret", "")
    if webhook_secret:
        sig = request.headers.get("signature", "")
        expected = hmac.new(webhook_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            logger.warning("SellApp webhook signature mismatch")
            return jsonify({"status": "error"}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error"}), 400

    event = data.get("event", "")
    charge = data.get("data", {})
    logger.info("SellApp webhook: %s", event)

    if event == "charge.completed":
        _handle_charge(charge)

    return jsonify({"status": "ok"})


def _handle_charge(charge):
    reference = charge.get("reference", "")
    email = charge.get("email", "")
    metadata = charge.get("metadata", {})
    ref_parts = _parse_reference(reference)

    user_id = int(metadata.get("user_id") or ref_parts.get("user", 0))
    tier_id = int(metadata.get("tier_id") or ref_parts.get("tier", 0))
    product_id = int(metadata.get("product_id") or ref_parts.get("product", 1))
    duration_days = int(metadata.get("duration_days") or ref_parts.get("days", 30))
    is_subscription = (metadata.get("is_subscription") or ref_parts.get("sub", "false")) == "true"

    user = db.session.get(User, user_id) if user_id else User.query.filter_by(email=email).first()
    if not user:
        logger.warning("No user for SellApp charge: %s", email)
        return

    tier = db.session.get(PricingTier, tier_id) if tier_id else None
    if not tier:
        return

    # Renewal — extend existing key
    if is_subscription:
        existing_order = Order.query.filter_by(
            user_id=user.id, tier_id=tier.id, status="completed"
        ).order_by(Order.created_at.desc()).first()
        if existing_order:
            key = Key.query.filter_by(order_id=existing_order.id).first()
            if key:
                key.expires_at = max(key.expires_at or datetime.utcnow(), datetime.utcnow()) + timedelta(days=duration_days)
                key.is_active = True
                db.session.commit()
                logger.info("Subscription renewed — key extended for user %s", user.id)
                return

    # New order — find pending or create
    order = Order.query.filter_by(
        user_id=user.id, tier_id=tier.id, status="pending"
    ).order_by(Order.created_at.desc()).first()

    if order and order.status == "completed":
        return

    if not order:
        order = Order(
            user_id=user.id, tier_id=tier.id,
            stripe_session_id=str(charge.get("id", "")),
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
        logger.info("Pool key assigned for SellApp order %s", order.id)
        return

    key_value = "BEAZT-" + secrets.token_hex(16).upper()
    order.status = "completed"
    key = Key(
        user_id=user.id, order_id=order.id,
        product_id=product_id, tier_id=tier_id,
        key_value=key_value, expires_at=expires_at,
        is_subscription=is_subscription,
    )
    db.session.add(key)
    db.session.commit()
    logger.info("Key auto-generated for SellApp order %s", order.id)
