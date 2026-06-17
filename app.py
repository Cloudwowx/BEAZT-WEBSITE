import os
from flask import Flask, render_template
from config import Config
from models import db, User, seed_products
from flask_login import LoginManager

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"

_basedir = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    static_folder=os.path.join(_basedir, "static"),
    static_url_path="/static",
)
app.config.from_object(Config)


@app.route("/ping")
def ping():
    return "ok"


db.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


try:
    from routes.main import main_bp
except Exception:
    main_bp = None
try:
    from routes.auth import auth_bp
except Exception:
    auth_bp = None
try:
    from routes.checkout import checkout_bp
except Exception:
    checkout_bp = None
try:
    from routes.admin import admin_bp
except Exception:
    admin_bp = None

if main_bp:
    app.register_blueprint(main_bp)
if auth_bp:
    app.register_blueprint(auth_bp, url_prefix="/auth")
if checkout_bp:
    app.register_blueprint(checkout_bp, url_prefix="/checkout")
if admin_bp:
    app.register_blueprint(admin_bp, url_prefix="/admin")


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.route("/webhooks/sellix", methods=["POST"])
def legacy_webhook():
    from routes.checkout import webhook
    return webhook()


@app.context_processor
def inject_discord():
    try:
        from config import get_discord_config
        cfg = get_discord_config()
        return {"discord_public_url": cfg["public_url"]}
    except Exception:
        return {"discord_public_url": "https://discord.gg/bU4tFA43KK"}


with app.app_context():
    db.create_all()

    import sqlite3
    try:
        _engine = db.engine
        _conn = _engine.raw_connection()
        _cursor = _conn.cursor()

        # Ensure products table has chairfbi_cheat_id
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "chairfbi_cheat_id" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN chairfbi_cheat_id VARCHAR(64)")
            _conn.commit()

        # Ensure products table has license_api_app_id
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "license_api_app_id" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN license_api_app_id VARCHAR(64)")
            _conn.commit()

        # Ensure products table has key_source
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "key_source" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN key_source VARCHAR(16) DEFAULT 'chairfbi'")
            _conn.commit()
            _cursor.execute("UPDATE products SET key_source='pool' WHERE chairfbi_cheat_id IS NULL OR chairfbi_cheat_id=''")
            _conn.commit()

        # Ensure products table has features_text
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "features_text" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN features_text TEXT")
            _conn.commit()

        # Ensure products table has buyer_notes
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "buyer_notes" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN buyer_notes TEXT")
            _conn.commit()

        # Ensure products table has visibility
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "visibility" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN visibility VARCHAR(16) DEFAULT 'public'")
            _conn.commit()
            _cursor.execute("UPDATE products SET visibility='private' WHERE key_source='pool'")
            _conn.commit()

        # Ensure pricing_tiers has billing_type, ivno_subscription_link
        _cursor.execute("PRAGMA table_info(pricing_tiers)")
        _tier_cols = [r[1] for r in _cursor.fetchall()]
        if "billing_type" not in _tier_cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN billing_type VARCHAR(16) DEFAULT 'one_time'")
            _conn.commit()
        if "ivno_subscription_link" not in _tier_cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN ivno_subscription_link VARCHAR(512)")
            _conn.commit()
        if "bundle_count" not in _tier_cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN bundle_count INTEGER DEFAULT 1")
            _conn.commit()

        # Ensure products table has venomcheats_slug
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "venomcheats_slug" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN venomcheats_slug VARCHAR(64)")
            _conn.commit()

        # Ensure products table has venomcheats_data
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "venomcheats_data" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN venomcheats_data TEXT")
            _conn.commit()

        # Ensure products table has last_synced_at
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "last_synced_at" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN last_synced_at DATETIME")
            _conn.commit()

        # Ensure products table has gallery_images
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "gallery_images" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN gallery_images TEXT")
            _conn.commit()

        # Ensure pricing_tiers table has is_subscription
        _cursor.execute("PRAGMA table_info(pricing_tiers)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "is_subscription" not in _cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN is_subscription BOOLEAN DEFAULT 0")
            _conn.commit()

        # Ensure pricing_tiers table has sellix_product_id
        _cursor.execute("PRAGMA table_info(pricing_tiers)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "sellix_product_id" not in _cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN sellix_product_id VARCHAR(64)")
            _conn.commit()

        # Ensure orders table has stripe_subscription_id
        _cursor.execute("PRAGMA table_info(orders)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "stripe_subscription_id" not in _cols:
            _cursor.execute("ALTER TABLE orders ADD COLUMN stripe_subscription_id VARCHAR(128)")
            _conn.commit()

        # Ensure keys table has is_subscription
        _cursor.execute("PRAGMA table_info(keys)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "is_subscription" not in _cols:
            _cursor.execute("ALTER TABLE keys ADD COLUMN is_subscription BOOLEAN DEFAULT 0")
            _conn.commit()

        # Ensure keys table has tier_id, assigned_at
        _cursor.execute("PRAGMA table_info(keys)")
        _key_cols = [r[1] for r in _cursor.fetchall()]
        if "tier_id" not in _key_cols:
            _cursor.execute("ALTER TABLE keys ADD COLUMN tier_id INTEGER REFERENCES pricing_tiers(id)")
            _conn.commit()
        if "assigned_at" not in _key_cols:
            _cursor.execute("ALTER TABLE keys ADD COLUMN assigned_at DATETIME")
            _conn.commit()

        _cursor.close()
        _conn.close()
    except Exception:
        pass

    try:
        mn_conn = db.engine.raw_connection()
        mc = mn_conn.cursor()
        for col, ddl in [
            ("bundle_count", "INTEGER DEFAULT 1"),
            ("ivno_subscription_link", "VARCHAR(512)"),
            ("billing_type", "VARCHAR(16) DEFAULT 'one_time'"),
            ("is_subscription", "BOOLEAN DEFAULT 0"),
            ("visibility", "VARCHAR(16) DEFAULT 'public'"),
            ("features_text", "TEXT"),
            ("buyer_notes", "TEXT"),
            ("venomcheats_data", "TEXT"),
            ("last_synced_at", "DATETIME"),
            ("gallery_images", "TEXT"),
            ("license_api_app_id", "VARCHAR(64)"),
        ]:
            try:
                mc.execute("ALTER TABLE products ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        for col, ddl in [
            ("bundle_count", "INTEGER DEFAULT 1"),
            ("ivno_subscription_link", "VARCHAR(512)"),
            ("billing_type", "VARCHAR(16) DEFAULT 'one_time'"),
            ("is_subscription", "BOOLEAN DEFAULT 0"),
        ]:
            try:
                mc.execute("ALTER TABLE pricing_tiers ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        for col, ddl in [
            ("is_subscription", "BOOLEAN DEFAULT 0"),
            ("tier_id", "INTEGER REFERENCES pricing_tiers(id)"),
            ("assigned_at", "DATETIME"),
        ]:
            try:
                mc.execute("ALTER TABLE keys ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        for col, ddl in [
            ("quantity", "INTEGER DEFAULT 1"),
            ("stripe_subscription_id", "VARCHAR(128)"),
        ]:
            try:
                mc.execute("ALTER TABLE orders ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        mn_conn.commit()
        mc.close()
        mn_conn.close()
    except Exception:
        pass

    try:
        from utils.kv_store import (
            restore_users_to_db, restore_products_to_db,
            restore_orders_to_db, restore_keys_to_db, restore_settings_to_db,
            start_backup_thread,
        )
        restore_users_to_db()
        restore_products_to_db()
        restore_orders_to_db()
        restore_keys_to_db()
        restore_settings_to_db()
        start_backup_thread(app, interval=120)
    except Exception:
        pass

    # Ensure license_api_app_id column exists on MySQL
    try:
        from sqlalchemy import text
        db.session.execute(text("ALTER TABLE products ADD COLUMN license_api_app_id VARCHAR(64)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    seed_products()

    try:
        from utils.sync import start_sync_service
        start_sync_service(app)
    except Exception:
        pass


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
