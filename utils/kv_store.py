import os
import json
import logging
import threading
import time

import requests
from flask import current_app

logger = logging.getLogger(__name__)

KV_REST_API_URL = os.getenv("KV_REST_API_URL", "")
KV_REST_API_TOKEN = os.getenv("KV_REST_API_TOKEN", "")
KV_AVAILABLE = bool(KV_REST_API_URL)

PRODUCT_FIELDS = [
    "name", "slug", "description", "image_url", "is_private",
    "chairfbi_cheat_id", "key_source", "visibility", "features_text",
    "buyer_notes", "venomcheats_slug", "venomcheats_data",
    "gallery_images", "last_synced_at",
]

_backup_thread = None
_backup_stop = threading.Event()


def _headers():
    if KV_REST_API_TOKEN:
        return {"Authorization": f"Bearer {KV_REST_API_TOKEN}"}
    return {}


def kv_get(key):
    if not KV_AVAILABLE:
        return None
    try:
        r = requests.get(
            f"{KV_REST_API_URL}/get/{key}",
            headers=_headers(),
            timeout=5,
        )
        if r.status_code == 200:
            return json.loads(r.json()["result"])
    except Exception as e:
        logger.warning("KV get failed for %s: %s", key, e)
    return None


def kv_set(key, value):
    if not KV_AVAILABLE:
        return
    try:
        requests.post(
            f"{KV_REST_API_URL}/set/{key}",
            json={"value": json.dumps(value, ensure_ascii=False)},
            headers=_headers(),
            timeout=5,
        )
    except Exception as e:
        logger.warning("KV set failed for %s: %s", key, e)


def backup_products():
    """Serialize all products to KV store."""
    if not KV_AVAILABLE:
        return

    try:
        from flask import current_app
        if not current_app:
            return
        from models import Product, db

        rows = Product.query.all()
        data = []
        for p in rows:
            row = {}
            for field in PRODUCT_FIELDS:
                val = getattr(p, field, None)
                if isinstance(val, bytes):
                    val = val.decode("utf-8", errors="replace")
                row[field] = val
            data.append(row)

        kv_set("beazt_products", data)
        logger.info("Backed up %d products to KV", len(data))
    except Exception as e:
        logger.warning("Product backup failed: %s", e)


def restore_products():
    """Restore products from KV store. Called during app startup."""
    if not KV_AVAILABLE:
        return None
    return kv_get("beazt_products")


def restore_products_to_db():
    """Restore backed-up products into the database if empty."""
    if not KV_AVAILABLE:
        return

    try:
        from models import Product, db

        backup = restore_products()
        if not backup:
            return

        for p_data in backup:
            slug = p_data.get("slug", "")
            if not slug:
                continue
            existing = Product.query.filter_by(slug=slug).first()
            if existing:
                continue

            kwargs = {k: v for k, v in p_data.items() if k in PRODUCT_FIELDS}
            if "created_at" not in kwargs:
                from datetime import datetime
                kwargs["created_at"] = datetime.utcnow()

            product = Product(**kwargs)
            db.session.add(product)

        db.session.commit()
        logger.info("Restored %d products from KV", len(backup))
    except Exception as e:
        logger.warning("Product restore failed: %s", e)


def _periodic_backup(app, interval=120):
    """Background thread that backs up products every N seconds."""
    logger.info("KV backup thread started (interval=%ds)", interval)
    while not _backup_stop.is_set():
        _backup_stop.wait(timeout=interval)
        if _backup_stop.is_set():
            break
        try:
            with app.app_context():
                backup_products()
        except Exception as e:
            logger.error("Periodic backup failed: %s", e)


def start_backup_thread(app, interval=120):
    global _backup_thread, _backup_stop
    if not KV_AVAILABLE:
        logger.info("KV not configured — backup thread skipped")
        return

    if _backup_thread and _backup_thread.is_alive():
        return

    _backup_stop.clear()
    _backup_thread = threading.Thread(
        target=_periodic_backup, args=(app, interval), daemon=True
    )
    _backup_thread.start()


def stop_backup_thread():
    _backup_stop.set()
