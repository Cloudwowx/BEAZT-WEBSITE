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
    is_private = db.Column(db.Boolean, default=True)
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
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    key_value = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    product = db.relationship("Product")


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
    from app import create_app

    app = create_app()
    with app.app_context():
        db.create_all()

        if User.query.filter_by(email="ludwig.streso@gmail.com").first() is None:
            admin = User(
                username="ludwig.streso@gmail.com",
                email="ludwig.streso@gmail.com",
                is_admin=True,
            )
            admin.set_password("58394Ludz$")
            db.session.add(admin)
            db.session.commit()
            print("Super admin account created.")

        if Product.query.count() == 0:
            product = Product(
                name="Rust External \u2014 Private",
                slug="rust-external-private",
                description=(
                    "Hardened external cheat for Rust with signature rotation, "
                    "custom stream-proof overlay, and private slot pool. "
                    "Vetted onboarding. Minimal footprint."
                ),
                image_url="/static/icons/rust_placeholder.jpg",
                is_private=True,
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
            print("Database seeded with Rust External Private product.")
