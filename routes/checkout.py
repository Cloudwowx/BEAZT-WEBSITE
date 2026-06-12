import secrets
import logging
from datetime import datetime, timedelta

import requests
from flask import Blueprint, request, redirect, jsonify, current_app, url_for
from flask_login import current_user, login_required
from models import db, User, PricingTier, Order, Key
from config import get_sellix_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

SELLIX_API = "https://api.sellix.gg/v1"


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
        if not tier.sellix_product_id:
            product_type = "license_key"
            payload = {
                "name": f"BEAZT - {tier.product.name} ({tier.label})",
                "type": product_type,
                "price_cents": tier.price_pence,
                "currency": "GBP",
            }
            resp = requests.post(
                f"{SELLIX_API}/products",
                json=payload,
                headers=_sellix_headers(),
                timeout=15,
            )
            data = resp.json()

            if resp.status_code not in (200, 201):
                error_msg = data.get("error") or data.get("type", str(data))
                logger.error("Sellix product creation failed: %s", error_msg)
                return jsonify({"error": str(error_msg)}), 500

            tier.sellix_product_id = data["id"]
            db.session.commit()
            logger.info("Created Sellix product %s for tier %s", tier.sellix_product_id, tier.label)

        order = Order(
            user_id=current_user.id,
            tier_id=tier.id,
            stripe_session_id=current_user.email,
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        buy_url = f"https://sellix.gg/buy/{tier.sellix_product_id}"
        return redirect(buy_url, code=303)

    except Exception as e:
        logger.exception("Sellix checkout failed")
        return jsonify({"error": str(e)}), 500


@checkout_bp.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error"}), 400

    event_type = payload.get("type", "")
    data = payload.get("data", {})
    logger.info("Sellix webhook: %s", event_type)

    if event_type == "order.paid":
        _handle_sellix_order(data)

    return jsonify({"status": "ok"})


def _handle_sellix_order(data):
    email = data.get("customer_email", "")
    items = data.get("items", [])
    if not items:
        logger.warning("Sellix order has no items")
        return

    sellix_prod_id = items[0].get("product_id")

    tier = PricingTier.query.filter_by(sellix_product_id=sellix_prod_id).first()
    if not tier:
        logger.warning("No matching tier for Sellix product %s", sellix_prod_id)
        return

    user = User.query.filter_by(email=email).first()
    if not user:
        logger.warning("No BEAZT user found for email %s", email)
        return

    order = Order.query.filter_by(
        user_id=user.id, tier_id=tier.id, status="pending"
    ).order_by(Order.created_at.desc()).first()

    if not order:
        order = Order(
            user_id=user.id,
            tier_id=tier.id,
            stripe_session_id=data.get("id", ""),
            status="completed",
        )
        db.session.add(order)
        db.session.flush()
    elif order.status == "completed":
        return

    duration_days = tier.duration_days
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    # Try pool key first
    pool_key = (
        Key.query
        .filter_by(product_id=tier.product_id, tier_id=tier.id, user_id=None, is_active=False)
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
        pool_key.is_subscription = tier.is_subscription
        order.status = "completed"
        db.session.commit()
        logger.info("Pool key assigned for order %s", order.id)
        return

    # Auto-generate key
    key_value = "BEAZT-" + secrets.token_hex(16).upper()
    order.status = "completed"
    key = Key(
        user_id=user.id,
        order_id=order.id,
        product_id=tier.product_id,
        tier_id=tier.id,
        key_value=key_value,
        expires_at=expires_at,
        is_subscription=tier.is_subscription,
    )
    db.session.add(key)
    db.session.commit()
    logger.info("Key auto-generated for order %s", order.id)
