import secrets
import logging
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key, Product, Setting
from config import get_ivno_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)


def _payfast_vars(order, amount, tier):
    pf_host = "https://www.payfast.co.za/eng/process"
    merchant_id = Setting.get("payfast_merchant_id") or ""
    merchant_key = Setting.get("payfast_merchant_key") or ""
    passphrase = Setting.get("payfast_passphrase") or ""
    name = f"BEAZT - {tier.product.name} ({tier.label})" if tier else "BEAZT Order"

    pf_data = {
        "merchant_id": merchant_id,
        "merchant_key": merchant_key,
        "return_url": url_for("main.my_keys", _external=True),
        "cancel_url": url_for("main.product_detail", slug=tier.product.slug, _external=True),
        "notify_url": url_for("checkout.payfast_notify", _external=True),
        "name_first": current_user.username or "",
        "email_address": current_user.email,
        "m_payment_id": str(order.id),
        "amount": f"{amount:.2f}",
        "item_name": name,
    }

    if passphrase:
        pf_string = "&".join(f"{k}={urlencode({k: pf_data[k]})[k]}" for k in sorted(pf_data) if pf_data[k])
        pf_string += f"&passphrase={urlencode({'passphrase': passphrase})['passphrase']}"
        pf_data["signature"] = hashlib.md5(pf_string.encode()).hexdigest()

    return pf_host, pf_data


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    quantity = int(request.form.get("quantity", 1))
    gateway = request.form.get("gateway", "payfast")

    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    order_total = tier.price_pounds * quantity

    if gateway == "ivno":
        if order_total < 20:
            return jsonify({"error": f"Minimum £20 required for card payments. Your total: £{order_total:.2f}"}), 400
        return _create_ivno_payment(tier, quantity, order_total)

    return _create_payfast_payment(tier, quantity, order_total)


def _create_ivno_payment(tier, quantity, order_total):
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
            fee_preference="absorb",
        )

        if not result.get("success") or not result.get("payment_url"):
            msg = result.get("message", "Payment initialization failed")
            return jsonify({"error": msg}), 500

        return jsonify({"payment_url": result["payment_url"]})
    except Exception as e:
        logger.exception("Ivno payment failed")
        return jsonify({"error": str(e)}), 500


def _create_payfast_payment(tier, quantity, order_total):
    order = Order(user_id=current_user.id, tier_id=tier.id, status="pending", quantity=quantity)
    db.session.add(order)
    db.session.flush()

    try:
        pf_host, pf_data = _payfast_vars(order, order_total, tier)
        return jsonify({
            "payment_url": pf_host,
            "payfast_data": pf_data,
            "payfast": True,
        })
    except Exception as e:
        logger.exception("PayFast payment failed")
        return jsonify({"error": str(e)}), 500


@checkout_bp.route("/payfast-notify", methods=["POST"])
def payfast_notify():
    pf_host, pf_data, pf_param_string = "https://www.payfast.co.za/eng/query/validate", {}, ""
    for k, v in request.form.items():
        if k != "signature":
            pf_data[k] = v
            pf_param_string += f"&{k}={v}"
    pf_param_string = pf_param_string[1:]

    import requests as _r
    resp = _r.post(pf_host, data=pf_data, params=pf_param_string, timeout=15)
    if resp.text != "VALID":
        return "INVALID", 400

    order_id = int(pf_data.get("m_payment_id", 0))
    order = db.session.get(Order, order_id)
    if not order:
        return "OK"

    amount_gross = float(pf_data.get("amount_gross", 0))
    expected = order.tier.price_pounds * (order.quantity or 1)
    if abs(amount_gross - expected) > 0.01:
        logger.warning("PayFast amount mismatch: got %s, expected %s", amount_gross, expected)
        return "OK"

    if order.status != "completed":
        handle_fulfillment(order)
    return "OK"


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
