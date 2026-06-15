import secrets
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key, Product
from config import get_ivno_config

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

IVNO_MIN_USD = 20.0
GBP_USD_RATE = 1.27


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    payment_method = request.form.get("payment_method", "ivno")

    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400

    tier = db.session.get(PricingTier, int(tier_id))
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    price_usd = tier.price_pounds * GBP_USD_RATE

    if payment_method == "nowpayments":
        return _nowpayments_session(tier)
    elif price_usd >= IVNO_MIN_USD:
        return _ivno_session(tier)
    else:
        return _nowpayments_session(tier)


def _ivno_session(tier):
    cfg = get_ivno_config()
    if not cfg["api_key"]:
        return jsonify({"error": "Ivno not configured"}), 500

    order = Order(user_id=current_user.id, tier_id=tier.id, status="pending")
    db.session.add(order)
    db.session.flush()

    try:
        from utils.ivno import IvnoPayments
        ivno = IvnoPayments(api_key=cfg["api_key"], api_secret=cfg["api_secret"])

        domain = request.host.split(":")[0] if ":" in (request.host or "") else request.host

        result = ivno.create_payment(
            amount=tier.price_pounds,
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


def _nowpayments_session(tier):
    from config import get_nowpayments_config
    cfg = get_nowpayments_config()
    if not cfg["api_key"]:
        return jsonify({"error": "NOWPayments not configured"}), 500

    order = Order(user_id=current_user.id, tier_id=tier.id, status="pending")
    db.session.add(order)
    db.session.flush()

    try:
        from utils.nowpayments import NOWPayments
        nwp = NOWPayments(api_key=cfg["api_key"])

        result = nwp.create_invoice(
            amount=tier.price_pounds,
            currency="GBP",
            order_id=f"BEAZT-NP-{order.id}",
            description=f"{tier.product.name} ({tier.label})" if tier.product else f"BEAZT License ({tier.label})",
            success_url=url_for("main.my_keys", _external=True),
            cancel_url=url_for("main.cheats", _external=True),
            ipn_callback_url=url_for("checkout.nowpayments_ipn", _external=True),
        )

        result_data = result.get("result", result)
        invoice_url = result_data.get("invoice_url", "")
        if not invoice_url:
            invoice_url = result.get("invoice_url") or result.get("checkout_url", "")
        if not invoice_url:
            return jsonify({"error": "Payment initialization failed"}), 500

        return jsonify({"payment_url": invoice_url})

    except Exception as e:
        err_msg = str(e)
        try:
            import json as _json
            if hasattr(e, "response") and e.response is not None:
                err_msg = _json.loads(e.response.text).get("message", err_msg)
        except Exception:
            pass
        logger.exception("NOWPayments session creation failed: %s", err_msg)
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


@checkout_bp.route("/nowpayments-ipn", methods=["POST"])
def nowpayments_ipn():
    data = request.get_json(silent=True) or {}
    payment_status = data.get("payment_status", "")
    order_id_raw = data.get("order_id", "")

    from config import get_nowpayments_config
    cfg = get_nowpayments_config()
    if cfg.get("ipn_secret"):
        from utils.nowpayments import verify_ipn
        if not verify_ipn(dict(data), cfg["ipn_secret"]):
            logger.warning("NOWPayments IPN signature invalid")
            return "FAIL"

    if not order_id_raw or not order_id_raw.startswith("BEAZT-NP-"):
        return "OK"

    try:
        order_id = int(order_id_raw.replace("BEAZT-NP-", ""))
    except (ValueError, TypeError):
        return "OK"

    order = db.session.get(Order, order_id)
    if not order:
        return "OK"

    if payment_status in ("finished", "confirmed") and order.status != "completed":
        handle_fulfillment(order)

    return "OK"


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
    key_values = []

    if cheat_id and api_token:
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=api_token, base_url=cfg.get("api_base"))
            result = cf.create_key(cheat_id=cheat_id, days=duration_days, amount=bundle_count)
            key_values = result.get("keys", [])
            chairfbi_key_id = ""
            chairfbi_cheat_id = cheat_id
        except Exception:
            logger.exception("ChairFBI key creation failed for order %s", order.id)

    if not key_values:
        key_values = ["BEAZT-" + secrets.token_hex(16).upper() for _ in range(bundle_count)]

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
