import os
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    keys = db.relationship("Key", backref="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(256), nullable=True)
    is_private = db.Column(db.Boolean, default=False)
    chairfbi_cheat_id = db.Column(db.String(64), nullable=True)
    key_source = db.Column(db.String(16), default="chairfbi")
    visibility = db.Column(db.String(16), default="public")
    features_text = db.Column(db.Text, nullable=True)
    buyer_notes = db.Column(db.Text, nullable=True)
    gallery_images = db.Column(db.Text, nullable=True)
    venomcheats_slug = db.Column(db.String(64), nullable=True)
    venomcheats_data = db.Column(db.Text, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tiers = db.relationship("PricingTier", backref="product", lazy="dynamic")


class PricingTier(db.Model):
    __tablename__ = "pricing_tiers"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    label = db.Column(db.String(64), nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    price_pence = db.Column(db.Integer, nullable=False)
    stripe_price_id = db.Column(db.String(128), nullable=True)

    orders = db.relationship("Order", backref="tier", lazy="dynamic")
    keys = db.relationship("Key", backref="pricing_tier", lazy="dynamic")

    @property
    def price_pounds(self):
        return self.price_pence / 100


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    tier_id = db.Column(db.Integer, db.ForeignKey("pricing_tiers.id"), nullable=False)
    stripe_session_id = db.Column(db.String(128), unique=True, nullable=True)
    status = db.Column(db.String(32), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    key = db.relationship("Key", backref="order", uselist=False)


class Key(db.Model):
    __tablename__ = "keys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    tier_id = db.Column(db.Integer, db.ForeignKey("pricing_tiers.id"), nullable=True)
    key_value = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    chairfbi_key_id = db.Column(db.String(64), nullable=True, index=True)
    chairfbi_cheat_id = db.Column(db.String(32), nullable=True)

    product = db.relationship("Product")
    tier = db.relationship("PricingTier", overlaps="keys,pricing_tier")


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        row = db.session.execute(
            db.select(Setting).filter_by(key=key)
        ).scalar_one_or_none()
        return row.value if row and row.value else default

    @staticmethod
    def set(key, value):
        row = db.session.execute(
            db.select(Setting).filter_by(key=key)
        ).scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))
        db.session.commit()


def seed_products():
    """Seed the database with the Rust External Private product and its pricing tiers."""
    admin_username = "admin"
    admin_password = "58394Ludz$"
    admin_email = os.getenv("ADMIN_EMAIL", "ludwig.streso@gmail.com").strip().lower()

    admin_user = User.query.filter_by(username=admin_username).first()
    if admin_user is None:
        admin_user = User.query.filter_by(email=admin_email).first()

    if admin_user is None:
        admin_user = User(
            username=admin_username,
            email=admin_email,
            is_admin=True,
            is_active=True,
        )
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        db.session.commit()
        print("Super admin account created.")
    else:
        changed = False

        if admin_user.username != admin_username:
            username_owner = User.query.filter_by(username=admin_username).first()
            if username_owner is None or username_owner.id == admin_user.id:
                admin_user.username = admin_username
                changed = True

        if not admin_user.is_admin:
            admin_user.is_admin = True
            changed = True

        if not admin_user.is_active:
            admin_user.is_active = True
            changed = True

        admin_user.set_password(admin_password)
        changed = True

        if changed:
            db.session.commit()
            print("Super admin account synced.")

    if Product.query.count() == 0:
        product = Product(
            name="Rust External - BeaZt Legit",
            slug="rust-external-private",
            description=(
                "Premium external performance suite with privacy-mode overlay "
                "and read-only architecture. Exclusive access with continuous "
                "updates and community support."
            ),
            features_text=(
                "Legit ESP suite with player and resource overlays\n"
                "Debug camera with free-roam spectator mode\n"
                "Distance and visibility tools with configurable ranges\n"
                "Legit-focused aim presets with natural curves\n"
                "Stream-safe privacy-mode overlay\n"
                "Private build with anti-detection updates\n"
                "Priority Discord setup support"
            ),
            buyer_notes=(
                "Windows 10/11 with a stable Rust install required\n"
                "Fast onboarding with Discord walkthrough guide\n"
                "Ticketed help for setup, HWID reset, and maintenance\n"
                "Loader download available in My Keys dashboard"
            ),
            image_url="/static/icons/rust_placeholder.jpg",
            is_private=False,
            key_source="pool",
            visibility="public",
        )
        db.session.add(product)
        db.session.flush()

        tiers = [
            PricingTier(
                product_id=product.id,
                label="1 Day",
                duration_days=1,
                price_pence=900,
            ),
            PricingTier(
                product_id=product.id,
                label="1 Week",
                duration_days=7,
                price_pence=2500,
            ),
            PricingTier(
                product_id=product.id,
                label="1 Month",
                duration_days=30,
                price_pence=4900,
            ),
            PricingTier(
                product_id=product.id,
                label="1 Year",
                duration_days=365,
                price_pence=39600,
            ),
        ]
        for tier in tiers:
            db.session.add(tier)

        db.session.commit()
        print("Database seeded with Performance Suite product.")
