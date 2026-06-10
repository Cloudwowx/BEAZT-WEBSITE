import requests
import logging

logger = logging.getLogger(__name__)


class ChairFBI:
    BASE = "https://access.chairfbi.com"
    TIMEOUT = 15

    def __init__(self, api_token=None, base_url=None):
        self.token = api_token
        self.base = base_url or self.BASE
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method, path, **kwargs):
        url = f"{self.base.rstrip('/')}/{path.lstrip('/')}"
        kwargs.setdefault("timeout", self.TIMEOUT)
        kwargs.setdefault("headers", self.headers)
        resp = requests.request(method, url, **kwargs)
        return resp

    def get_cheats(self):
        resp = self._request("GET", "/cheats")
        resp.raise_for_status()
        return resp.json()

    def get_balance(self):
        resp = self._request("GET", "/store/balance")
        resp.raise_for_status()
        return resp.json()

    def get_store_info(self):
        resp = self._request("GET", "/store")
        resp.raise_for_status()
        return resp.json()

    def create_key(self, cheat_id, days, notes=None):
        payload = {"cheat_id": cheat_id, "days": days}
        if notes:
            payload["notes"] = notes
        resp = self._request("POST", "/keys", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data

    def get_key(self, key_id):
        resp = self._request("GET", f"/keys/{key_id}")
        resp.raise_for_status()
        return resp.json()

    def list_keys(self, page=1, per_page=50, cheat_id=None):
        params = {"page": page, "per_page": per_page}
        if cheat_id:
            params["cheat_id"] = cheat_id
        resp = self._request("GET", "/keys", params=params)
        resp.raise_for_status()
        return resp.json()

    def revoke_key(self, key_id):
        resp = self._request("DELETE", f"/keys/{key_id}")
        resp.raise_for_status()
        return resp.status_code in (200, 204)

    def test_connection(self):
        try:
            resp = self._request("GET", "/store")
            return resp.status_code == 200, resp.json()
        except Exception as e:
            return False, str(e)
