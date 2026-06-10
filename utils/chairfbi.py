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

    # -- Status --
    def get_cheats(self):
        """GET /api/status - returns cheat availability list [{id, name, active, price_type}]"""
        resp = self._request("GET", "/api/status")
        resp.raise_for_status()
        return resp.json()

    def get_cheat_bases(self):
        """GET /api/status-bases - returns cheat base status list"""
        resp = self._request("GET", "/api/status-bases")
        resp.raise_for_status()
        return resp.json()

    # -- Store --
    def get_store_info(self):
        """GET /api/store - returns store info including balance"""
        resp = self._request("GET", "/api/store")
        resp.raise_for_status()
        return resp.json()

    def get_balance(self):
        """Returns balance integer from /api/store"""
        store = self.get_store_info()
        if isinstance(store, dict):
            return store.get("balance")
        return store

    # -- Cheats (paginated) --
    def list_cheats(self, page=1, per_page=50, sort=None, filter_str=None):
        """GET /api/cheats - paginated cheat list with meta"""
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if filter_str:
            params["filter"] = filter_str
        resp = self._request("GET", "/api/cheats", params=params)
        resp.raise_for_status()
        return resp.json()

    # -- Keys --
    def create_key(self, cheat_id, days, notes=None, prefix=None):
        """POST /api/keys - creates 1 key, returns {balance, keys: [string]}"""
        payload = {"cheat": int(cheat_id), "amount": 1, "days": days}
        if prefix:
            payload["prefix"] = prefix
        if notes:
            payload["notes"] = notes
        resp = self._request("POST", "/api/keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def list_keys(self, page=1, per_page=50, cheat_id=None, sort=None, filter_str=None):
        """GET /api/keys - paginated key list with meta.data"""
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if filter_str:
            params["filter"] = filter_str
        resp = self._request("GET", "/api/keys", params=params)
        resp.raise_for_status()
        return resp.json()

    def update_keys(self, keys, hwid=None, freezed=None, locked=None, vouche=None, notes=None):
        """PUT /api/keys - update keys (hwid reset, freeze, lock, vouche)"""
        payload = {"keys": keys}
        if hwid is not None:
            payload["hwid"] = hwid
        if freezed is not None:
            payload["freezed"] = freezed
        if locked is not None:
            payload["locked"] = locked
        if vouche is not None:
            payload["vouche"] = vouche
        if notes is not None:
            payload["notes"] = notes
        resp = self._request("PUT", "/api/keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def revoke_key(self, key_id):
        """Lock a key via PUT /api/keys"""
        return self.update_keys(keys=[key_id], locked=True)

    def test_connection(self):
        try:
            resp = self._request("GET", "/api/store")
            return resp.status_code == 200, resp.json()
        except Exception as e:
            return False, str(e)
