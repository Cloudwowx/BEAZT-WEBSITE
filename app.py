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

db.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


from routes.main import main_bp
from routes.auth import auth_bp
from routes.checkout import checkout_bp
from routes.admin import admin_bp

app.register_blueprint(main_bp)
app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(checkout_bp, url_prefix="/checkout")
app.register_blueprint(admin_bp, url_prefix="/admin")


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.context_processor
def inject_discord():
    try:
        from config import get_discord_config
        cfg = get_discord_config()
        return {"discord_public_url": cfg["public_url"]}
    except Exception:
        return {"discord_public_url": "https://discord.gg/TvxrADZhNR"}


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

    from utils.kv_store import restore_products_to_db, start_backup_thread
    try:
        restore_products_to_db()
    except Exception:
        pass

    seed_products()

    try:
        start_backup_thread(app, interval=120)
    except Exception:
        pass

    try:
        from utils.sync import start_sync_service
        start_sync_service(app)
    except Exception:
        pass


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
