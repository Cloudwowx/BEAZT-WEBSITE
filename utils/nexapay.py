import hashlib
import hmac
import requests
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://nexapay.one/api/v1"
TIMEOUT = 30


class NexaPay:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base = base_url or BASE_URL

    def _headers(self):
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def create_payment(self, amount, currency, description=None, customer_email=None,
                       success_url=None, cancel_url=None, callback_url=None, crypto="USDC"):
        payload = {
            "amount": amount,
            "currency": currency,
            "crypto": crypto,
        }
        if description:
            payload["description"] = description
        if customer_email:
            payload["customer_email"] = customer_email
        if success_url:
            payload["success_url"] = success_url
        if cancel_url:
            payload["cancel_url"] = cancel_url
        if callback_url:
            payload["callback_url"] = callback_url

        url = f"{self.base}/payments"
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_payment(self, order_id):
        url = f"{self.base}/payments/{order_id}"
        resp = requests.get(url, headers=self._headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()


def verify_webhook(timestamp, raw_body, signature, webhook_secret):
    if not webhook_secret or not signature:
        return True

    signed_payload = f"{timestamp}.{raw_body}"
    expected = hmac.new(
        webhook_secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    expected_sig = f"sha256={expected}"

    if not hmac.compare_digest(signature, expected_sig):
        return False

    try:
        ts = int(timestamp)
        import time
        if abs(time.time() * 1000 - ts) > 5 * 60 * 1000:
            logger.warning("NexaPay webhook expired, timestamp=%s", timestamp)
            return False
    except (ValueError, TypeError):
        return False

    return True
