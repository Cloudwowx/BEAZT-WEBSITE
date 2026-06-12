import secrets
import json
import logging
from datetime import datetime, timedelta

import requests
from flask import Blueprint, request, redirect, jsonify, current_app, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key
from config import get_sellix_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

SELLIX_API = "https://sellix.io/v1"


def _sellix_headers():
    cfg = get_sellix_config()
    return {"Authorization": f"Bearer {cfg['api_key']}"}


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    cfg = get_sellix_config()
    if not cfg["api_key"]:
        return jsonify({"error": "Sellix API key not configured"}), 500

    try:
        payload = {
            "title": f"BEAZT - {tier.product.name} ({tier.label})",
            "currency": "GBP",
            "value": tier.price_pounds,
            "email": current_user.email,
            "webhook": url_for("checkout.webhook", _external=True),
            "return_url": url_for("main.my_keys", _external=True),
            "custom_fields": {
                "user_id": str(current_user.id),
                "tier_id": str(tier.id),
                "product_id": str(tier.product_id),
                "product_slug": tier.product.slug,
                "duration_days": str(tier.duration_days),
                "is_subscription": str(tier.is_subscription).lower(),
            },
        }

        if tier.is_subscription:
            payload["recurring"] = True
            payload["recurring_interval"] = tier.duration_days

        resp = requests.post(
            f"{SELLIX_API}/payments",
            json=payload,
            headers=_sellix_headers(),
            timeout=15,
        )
        data = resp.json()

        if resp.status_code != 200 or data.get("status") != 200:
            error_msg = data.get("message", data.get("error", "Unknown error"))
            logger.error("Sellix payment creation failed: %s", error_msg)
            return jsonify({"error": str(error_msg)}), 500

        sellix_uniqid = data["data"]["uniqid"]
        payment_url = data["data"]["url"]

        order = Order(
            user_id=current_user.id,
            tier_id=tier.id,
            stripe_session_id=sellix_uniqid,
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        return redirect(payment_url, code=303)
    except Exception as e:
        logger.exception("Sellix checkout failed")
        return jsonify({"error": str(e)}), 500


@checkout_bp.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error", "error": "Invalid payload"}), 400

    cfg = get_sellix_config()
    webhook_secret = cfg.get("webhook_secret", "")
    if webhook_secret:
        header_secret = request.headers.get("X-Sellix-Webhook", "")
        if header_secret != webhook_secret:
            logger.warning("Sellix webhook secret mismatch")
            return jsonify({"status": "error"}), 403

    event = payload.get("event", "")
    order_data = payload.get("data", {})
    logger.info("Sellix webhook: %s", event)

    if event in ("order:paid", "order:completed"):
        _handle_payment(order_data)

    return jsonify({"status": "ok"})


def _handle_payment(order_data):
    uniqid = order_data.get("uniqid")
    if not uniqid:
        return

    order = Order.query.filter_by(stripe_session_id=uniqid).first()
    if not order:
        logger.warning("No order found for Sellix uniqid: %s", uniqid)
        return

    if order.status == "completed":
        return

    custom = order_data.get("custom_fields", {})
    if not custom:
        custom = {}

    duration_days = int(custom.get("duration_days", order.tier.duration_days if order.tier else 30))
    product_id = int(custom.get("product_id", order.tier.product_id if order.tier else 1))
    tier_id = int(custom.get("tier_id", order.tier_id if order.tier_id else 0))
    is_subscription = custom.get("is_subscription", "false") == "true"
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    from models import Product
    product = db.session.get(Product, product_id)

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
        logger.info("Pool key assigned for order %s", order.id)
        return

    # 2) Auto-generate key
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
    )
    db.session.add(key)
    db.session.commit()
    logger.info("Key auto-generated for order %s", order.id)
