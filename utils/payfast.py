import hashlib
import requests
import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

PAYFAST_LIVE = "https://www.payfast.co.za/eng"
PAYFAST_SANDBOX = "https://sandbox.payfast.co.za/eng"

_ZAR_RATE = None
_ZAR_RATE_TS = 0


def _get_zar_rate():
    import time
    global _ZAR_RATE, _ZAR_RATE_TS
    now = time.time()
    if _ZAR_RATE and (now - _ZAR_RATE_TS) < 600:
        return _ZAR_RATE

    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/GBP", timeout=10)
        data = resp.json()
        _ZAR_RATE = data.get("rates", {}).get("ZAR", 23.5)
        _ZAR_RATE_TS = now
    except Exception:
        logger.warning("Exchange rate API failed, using fallback")
        _ZAR_RATE = _ZAR_RATE or 23.5
    return _ZAR_RATE


def gbp_to_zar(gbp_amount):
    rate = _get_zar_rate()
    return round(gbp_amount * rate, 2)


def _build_signature(data, passphrase):
    from urllib.parse import quote_plus
    fields = []
    for k in sorted(data.keys()):
        if k == "signature":
            continue
        v = str(data.get(k, "")).strip()
        fields.append(f"{k}={quote_plus(v)}")
    if passphrase:
        fields.append(f"passphrase={quote_plus(str(passphrase).strip())}")
    raw = "&".join(fields)
    return hashlib.md5(raw.encode()).hexdigest()


def build_payment_form(amount_zar, item_name, order_id, return_url, cancel_url, notify_url,
                       merchant_id, merchant_key, passphrase,
                       email=None, first_name=None, last_name=None):
    data = {
        "merchant_id": str(merchant_id),
        "merchant_key": str(merchant_key),
        "amount": f"{amount_zar:.2f}",
        "item_name": item_name[:100],
        "m_payment_id": str(order_id),
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notify_url": notify_url,
    }
    if email:
        data["email_address"] = email
    if first_name:
        data["name_first"] = first_name[:100]
    if last_name:
        data["name_last"] = last_name[:100]

    data["signature"] = _build_signature(data, passphrase)
    return {
        "action_url": f"{PAYFAST_LIVE}/process",
        "fields": data,
    }


def validate_itn(request_form):
    import time
    data = dict(request_form)
    passphrase = ""
    try:
        from config import get_payfast_config
        passphrase = get_payfast_config().get("passphrase", "")
    except Exception:
        pass

    received_sig = data.pop("signature", "")
    computed = _build_signature(data, passphrase)
    if received_sig != computed:
        return False, "Signature mismatch"

    pf_param_string = urlencode(data)
    try:
        resp = requests.post(
            f"{PAYFAST_LIVE}/query/validate",
            data=pf_param_string,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        return resp.text == "VALID", resp.text
    except Exception as e:
        return False, str(e)
