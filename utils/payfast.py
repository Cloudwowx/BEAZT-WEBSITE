import hashlib
import requests
import logging

logger = logging.getLogger(__name__)

PAYFAST_LIVE = "https://www.payfast.co.za/eng"
PAYFAST_SANDBOX = "https://sandbox.payfast.co.za/eng"

PAYFAST_FIELD_ORDER = [
    "merchant_id", "merchant_key", "return_url", "cancel_url",
    "notify_url",
    "name_first", "name_last", "email_address", "cell_number",
    "m_payment_id", "amount", "item_name", "item_description",
    "custom_int1", "custom_int2", "custom_int3", "custom_int4", "custom_int5",
    "custom_str1", "custom_str2", "custom_str3", "custom_str4", "custom_str5",
    "email_confirmation", "confirmation_address",
    "payment_method",
    "subscription_type", "billing_date", "recurring_amount", "frequency", "cycles",
]

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


def _build_signature(data, passphrase, sort_keys=False):
    from urllib.parse import quote_plus

    cleaned = {}
    keys_iter = sorted(data.keys()) if sort_keys else data.keys()
    for k in keys_iter:
        if k == "signature":
            continue
        v = data.get(k)
        if v is None:
            continue
        vs = str(v).strip()
        if not vs:
            continue
        cleaned[k] = vs

    if not sort_keys:
        prio = {k: i for i, k in enumerate(PAYFAST_FIELD_ORDER)}
        ordered = sorted(cleaned.keys(), key=lambda k: prio.get(k, len(PAYFAST_FIELD_ORDER)))
    else:
        ordered = sorted(cleaned.keys())

    parts = []
    for k in ordered:
        parts.append(f"{k}={quote_plus(cleaned[k])}")
    param_string = "&".join(parts)

    if passphrase:
        param_string += f"&passphrase={quote_plus(str(passphrase).strip())}"

    return hashlib.md5(param_string.encode()).hexdigest()


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

    data["signature"] = _build_signature(data, passphrase, sort_keys=False)
    return {
        "action_url": f"{PAYFAST_LIVE}/process",
        "fields": data,
    }


def validate_itn(request_form):
    import time
    from urllib.parse import urlencode

    data = dict(request_form)
    passphrase = ""
    try:
        from config import get_payfast_config
        passphrase = get_payfast_config().get("passphrase", "")
    except Exception:
        pass

    received_sig = data.pop("signature", "")
    computed = _build_signature(data, passphrase, sort_keys=True)
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
