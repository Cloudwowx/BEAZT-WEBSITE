import secrets
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key, Product
from config import get_ivno_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    quantity = int(request.form.get("quantity", 1))

    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    order_total = tier.price_pounds * quantity

    cfg = get_ivno_config()
    if not cfg["api_key"]:
        return jsonify({"error": "Ivno not configured"}), 500

    order = Order(user_id=current_user.id, tier_id=tier.id, status="pending", quantity=quantity)
    db.session.add(order)
    db.session.flush()

    try:
        from utils.ivno import IvnoPayments
        ivno = IvnoPayments(api_key=cfg["api_key"], api_secret=cfg["api_secret"])

        domain = request.host.split(":")[0] if ":" in (request.host or "") else request.host

        result = ivno.create_payment(
            amount=order_total,
            currency="GBP",
            order_id=f"BEAZT-{order.id}",
            return_url=url_for("main.my_keys", _external=True),
            email=current_user.email,
            webhook_url=url_for("checkout.ivno_webhook", _external=True),
            domain=domain,
        )

        if not result.get("success") or not result.get("payment_url"):
            msg = result.get("message", "Payment initialization failed")
            return jsonify({"error": msg}), 500

        return jsonify({"payment_url": result["payment_url"]})

    except Exception as e:
        err_msg = str(e)
        try:
            import json as _json
            if hasattr(e, "response") and e.response is not None:
                err_msg = _json.loads(e.response.text).get("message", err_msg)
        except Exception:
            pass
        logger.exception("Ivno session creation failed: %s", err_msg)
        return jsonify({"error": err_msg}), 500


@checkout_bp.route("/ivno-webhook", methods=["POST"])
def ivno_webhook():
    data = request.get_json(silent=True) or {}
    status = data.get("status", "")
    event = data.get("event", "")
    order_id_raw = data.get("order_id", "")

    if not order_id_raw or not order_id_raw.startswith("BEAZT-"):
        return jsonify({"received": True})

    try:
        order_id = int(order_id_raw.replace("BEAZT-", ""))
    except (ValueError, TypeError):
        return jsonify({"received": True})

    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({"received": True})

    if event != "payment.updated":
        return jsonify({"received": True})

    if status == "completed" and order.status != "completed":
        handle_fulfillment(order)

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
        return

    if product and product.key_source == "pool":
        order.status = "awaiting_keys"
        db.session.commit()
        return

    from config import get_chairfbi_config
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    cheat_id = product.chairfbi_cheat_id if product else ""

    bundle_count = getattr(tier, "bundle_count", 1) or 1
    buy_quantity = getattr(order, "quantity", 1) or 1
    total_keys = bundle_count * buy_quantity
    key_values = []

    if cheat_id and api_token:
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=api_token, base_url=cfg.get("api_base"))
            result = cf.create_key(cheat_id=cheat_id, days=duration_days, amount=total_keys)
            key_values = result.get("keys", [])
        except Exception:
            logger.exception("ChairFBI key creation failed for order %s", order.id)

    if not key_values:
        key_values = ["BEAZT-" + secrets.token_hex(16).upper() for _ in range(total_keys)]

    order.status = "completed"
    for kv in key_values:
        key = Key(
            user_id=order.user_id,
            order_id=order.id,
            product_id=product_id,
            tier_id=tier.id,
            key_value=kv,
            expires_at=expires_at,
            chairfbi_key_id=kv if cheat_id else None,
            chairfbi_cheat_id=cheat_id if cheat_id else None,
        )
        db.session.add(key)
    db.session.commit()
    try:
        from utils.kv_store import backup_everything
        backup_everything()
    except Exception:
        pass
