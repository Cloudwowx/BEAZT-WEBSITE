import secrets
import logging
import hashlib
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key, Product, Setting
from config import get_ivno_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

_ZAR_RATE = None
_ZAR_RATE_TIME = None


def _get_gbp_to_zar():
    import requests as _r
    global _ZAR_RATE, _ZAR_RATE_TIME
    if _ZAR_RATE and _ZAR_RATE_TIME and (datetime.utcnow() - _ZAR_RATE_TIME).seconds < 600:
        return _ZAR_RATE
    try:
        resp = _r.get("https://open.er-api.com/v6/latest/GBP", timeout=5)
        data = resp.json()
        _ZAR_RATE = data["rates"]["ZAR"]
        _ZAR_RATE_TIME = datetime.utcnow()
        return _ZAR_RATE
    except Exception:
        return 24.0  # fallback GBP→ZAR


def _payfast_vars(order, amount, tier):
    pf_host = "https://www.payfast.co.za/eng/process"
    merchant_id = Setting.get("payfast_merchant_id") or ""
    merchant_key = Setting.get("payfast_merchant_key") or ""
    passphrase = Setting.get("payfast_passphrase") or ""
    name = f"BEAZT - {tier.product.name}" if tier else "BEAZT Order"

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

    from urllib.parse import quote_plus
    WHITELIST = [
        "merchant_id", "merchant_key", "return_url", "cancel_url",
        "notify_url", "name_first", "name_last", "email_address",
        "cell_number", "m_payment_id", "amount", "item_name",
        "item_description", "custom_int1", "custom_int2", "custom_int3",
        "custom_int4", "custom_int5", "custom_str1", "custom_str2",
        "custom_str3", "custom_str4", "custom_str5",
        "email_confirmation", "confirmation_address", "currency",
        "payment_method", "subscription_type", "billing_date",
        "recurring_amount", "frequency", "cycles",
    ]

    param_string = ""
    for field in WHITELIST:
        if field in pf_data and pf_data[field]:
            val = str(pf_data[field]).strip()
            param_string += f"&{field}={quote_plus(val)}"
    param_string = param_string.lstrip("&")
    if passphrase:
        param_string += "&passphrase=" + quote_plus(passphrase.strip())

    pf_data["signature"] = hashlib.md5(param_string.encode()).hexdigest()
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
    db.session.commit()

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
    db.session.commit()

    try:
        zar_amount = round(order_total * _get_gbp_to_zar(), 2)
        pf_host, pf_data = _payfast_vars(order, zar_amount, tier)
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
    logger.info("PayFast ITN received: %s", dict(request.form))
    pf_host, pf_data, pf_param_string = "https://www.payfast.co.za/eng/query/validate", {}, ""
    for k, v in request.form.items():
        if k != "signature":
            pf_data[k] = v
            pf_param_string += f"&{k}={v}"
    pf_param_string = pf_param_string[1:]

    import requests as _r
    resp = _r.post(pf_host, data=pf_data, params=pf_param_string, timeout=15)
    logger.info("PayFast validation response: %s", resp.text)
    if resp.text != "VALID":
        return "INVALID", 400

    order_id = int(pf_data.get("m_payment_id", 0))
    logger.info("PayFast ITN for order %s, payment_status=%s", order_id, pf_data.get("payment_status", "?"))
    order = db.session.get(Order, order_id)
    if not order:
        logger.warning("PayFast ITN: order %s not found", order_id)
        return "OK"

    if order.status != "completed":
        logger.info("Fulfilling order %s", order.id)
        handle_fulfillment(order)
    else:
        logger.info("Order %s already completed", order.id)
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

    if status == "completed" and order.status != "completed":
        handle_fulfillment(order)

    return jsonify({"received": True})


def handle_fulfillment(order):
    tier = order.tier
    if not tier:
        logger.warning("Fulfill: no tier for order %s", order.id)
        return

    product = tier.product
    product_id = product.id if product else 1
    duration_days = tier.duration_days
    expires_at = datetime.utcnow() + timedelta(days=duration_days)
    total_keys = (getattr(tier, "bundle_count", 1) or 1) * (getattr(order, "quantity", 1) or 1)

    logger.info("Fulfilling order %s — product=%s tier=%s key_source=%s app_id=%s",
                order.id, product.name if product else "?", tier.label,
                product.key_source if product else "?", product.license_api_app_id if product else "?")

    # 1) License API — primary auto-generate source
    if product and product.license_api_app_id:
        try:
            from config import Config
            from utils.license_api import LicenseAPI
            api = LicenseAPI(api_token=Config.LICENSE_API_TOKEN, base_url=Config.LICENSE_API_URL)
            keys_data = api.create_keys(app_id=product.license_api_app_id, duration_days=duration_days, quantity=total_keys)
            if isinstance(keys_data, list) and keys_data:
                order.status = "completed"
                for k in keys_data:
                    kv = k if isinstance(k, str) else (k.get("key") or k.get("license") or str(k))
                    key = Key(user_id=order.user_id, order_id=order.id, product_id=product_id,
                              tier_id=tier.id, key_value=kv, expires_at=expires_at, is_active=True)
                    db.session.add(key)
                db.session.commit()
                logger.info("License API generated %d key(s) for order %s", len(keys_data), order.id)
                return
        except Exception:
            logger.exception("License API failed for order %s — falling back", order.id)

    # 2) Pool key — fallback if available
    pool_key = (Key.query.filter_by(product_id=product_id, tier_id=tier.id, user_id=None, is_active=False)
                .order_by(Key.created_at.asc()).first())
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

    # 3) ChairFBI — final fallback
    from config import get_chairfbi_config
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    cheat_id = product.chairfbi_cheat_id if product else ""
    bundle_count = getattr(tier, "bundle_count", 1) or 1
    buy_quantity = getattr(order, "quantity", 1) or 1
    total_keys_cf = bundle_count * buy_quantity
    key_values = []

    if cheat_id and api_token:
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=api_token, base_url=cfg.get("api_base"))
            result = cf.create_key(cheat_id=cheat_id, days=duration_days, amount=total_keys_cf)
            key_values = result.get("keys", [])
        except Exception:
            logger.exception("ChairFBI key creation failed for order %s", order.id)

    if not key_values:
        key_values = ["BEAZT-" + secrets.token_hex(16).upper() for _ in range(total_keys_cf)]

    order.status = "completed"
    for kv in key_values:
        key = Key(user_id=order.user_id, order_id=order.id, product_id=product_id,
                  tier_id=tier.id, key_value=kv, expires_at=expires_at, is_active=True,
                  chairfbi_key_id=kv if cheat_id else None, chairfbi_cheat_id=cheat_id if cheat_id else None)
        db.session.add(key)
    db.session.commit()
