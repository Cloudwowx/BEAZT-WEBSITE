import secrets
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key, Product
from config import get_nexapay_config

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

    cfg = get_nexapay_config()
    if not cfg["api_key"]:
        return jsonify({"error": "NexaPay API key not configured"}), 500

    order = Order(
        user_id=current_user.id,
        tier_id=tier.id,
        status="pending",
    )
    db.session.add(order)
    db.session.flush()

    try:
        from utils.nexapay import NexaPay
        nxp = NexaPay(api_key=cfg["api_key"])

        product = tier.product

        result = nxp.create_payment(
            amount=tier.price_pounds,
            currency="GBP",
            description=f"{product.name} ({tier.label})" if product else f"BEAZT License ({tier.label})",
            customer_email=current_user.email,
            success_url=url_for("main.my_keys", _external=True),
            cancel_url=url_for("main.cheats", _external=True),
            callback_url=url_for("checkout.nexapay_webhook", _external=True),
        )

        if not result.get("success") or not result.get("payment", {}).get("checkout_url"):
            logger.error("NexaPay payment creation failed: %s", result)
            return jsonify({"error": "Payment initialization failed"}), 500

        checkout_url = result["payment"]["checkout_url"]
        order_id_nxp = result["payment"].get("order_id", "")
        order.stripe_session_id = checkout_url
        db.session.commit()
        return jsonify({"payment_url": checkout_url})

    except Exception as e:
        err_msg = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                import json as _json
                err_msg = _json.loads(e.response.text).get("message", err_msg)
        except Exception:
            pass
        logger.exception("NexaPay session creation failed: %s", err_msg)
        return jsonify({"error": err_msg}), 500


@checkout_bp.route("/nexapay-webhook", methods=["POST"])
def nexapay_webhook():
    raw_body = request.get_data(as_text=True)
    data = request.get_json(silent=True) or {}
    signature = request.headers.get("X-NexaPay-Signature", "")
    timestamp = request.headers.get("X-NexaPay-Timestamp", "")

    cfg = get_nexapay_config()
    from utils.nexapay import verify_webhook
    if not verify_webhook(timestamp, raw_body, signature, cfg.get("webhook_secret", "")):
        logger.warning("NexaPay webhook signature verification failed")
        return jsonify({"error": "Invalid signature"}), 401

    status = data.get("status", "")
    nxp_order_id = data.get("order_id", "")

    if status == "completed":
        orders = Order.query.filter_by(status="pending").order_by(Order.id.desc()).limit(5).all()
        for order in orders:
            if order.status != "completed":
                handle_fulfillment(order)
                break
    elif status in ("expired", "failed"):
        orders = Order.query.filter_by(status="pending").order_by(Order.id.desc()).limit(5).all()
        for order in orders:
            if order.status != "completed":
                order.status = "failed"
                db.session.commit()
                break

    return jsonify({"received": True})


def handle_fulfillment(order):
    tier = order.tier
    if not tier:
        return

    product = tier.product
    product_id = product.id if product else 1
    duration_days = tier.duration_days
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    pool_key = (
        Key.query
        .filter_by(product_id=product_id, tier_id=tier.id, user_id=None, is_active=False)
        .order_by(Key.created_at.asc())
        .first()
    )
    if pool_key:
        pool_key.user_id = order.user_id
        pool_key.order_id = order.id
        pool_key.expires_at = expires_at
        pool_key.assigned_at = datetime.utcnow()
        pool_key.is_active = True
        order.status = "completed"
        db.session.commit()
        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass
        return

    if product and product.key_source == "pool":
        order.status = "awaiting_keys"
        db.session.commit()
        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass
        return

    from config import get_chairfbi_config
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    cheat_id = product.chairfbi_cheat_id if product else ""

    key_value = ""
    chairfbi_key_id = None
    chairfbi_cheat_id = None

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
        tier_id=tier.id,
        key_value=key_value,
        expires_at=expires_at,
        chairfbi_key_id=chairfbi_key_id,
        chairfbi_cheat_id=chairfbi_cheat_id,
    )
    db.session.add(key)
    db.session.commit()
    try:
        from utils.kv_store import backup_everything
        backup_everything()
    except Exception:
        pass
