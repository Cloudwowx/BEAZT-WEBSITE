from functools import wraps
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from models import db, User, Product, PricingTier, Order, Key, Setting
from config import get_stripe_config

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/")
@admin_required
def dashboard():
    total_users = User.query.count()
    total_keys = Key.query.count()
    active_keys = Key.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    completed_orders = Order.query.filter_by(status="completed").count()
    total_products = Product.query.count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_keys = Key.query.order_by(Key.created_at.desc()).limit(5).all()

    revenue_pence = 0
    completed = Order.query.filter_by(status="completed").all()
    for o in completed:
        if o.tier:
            revenue_pence += o.tier.price_pence

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_keys=total_keys,
        active_keys=active_keys,
        total_orders=total_orders,
        completed_orders=completed_orders,
        total_products=total_products,
        revenue_pounds=revenue_pence / 100,
        recent_users=recent_users,
        recent_keys=recent_keys,
    )


@admin_bp.route("/users")
@admin_required
def users():
    page = request.args.get("page", 1, type=int)
    users_list = User.query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    return render_template("admin/users.html", users=users_list)


@admin_bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    keys = Key.query.filter_by(user_id=user.id).order_by(Key.created_at.desc()).all()
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    return render_template("admin/user_detail.html", target_user=user, keys=keys, orders=orders)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.is_admin:
        flash("Cannot disable an admin account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"User {'activated' if user.is_active else 'deactivated'}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.is_admin:
        flash("Cannot delete an admin account.", "error")
        return redirect(url_for("admin.users"))
    Key.query.filter_by(user_id=user.id).delete()
    Order.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("User and all associated data deleted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/keys")
@admin_required
def keys():
    page = request.args.get("page", 1, type=int)
    keys_list = Key.query.order_by(Key.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False
    )
    return render_template("admin/keys.html", keys=keys_list)


@admin_bp.route("/keys/<int:key_id>/toggle", methods=["POST"])
@admin_required
def toggle_key(key_id):
    key = db.session.get(Key, key_id)
    if not key:
        abort(404)
    key.is_active = not key.is_active
    db.session.commit()
    flash(f"Key {'activated' if key.is_active else 'revoked'}.", "success")
    return redirect(url_for("admin.keys"))


@admin_bp.route("/keys/<int:key_id>/delete", methods=["POST"])
@admin_required
def delete_key(key_id):
    key = db.session.get(Key, key_id)
    if not key:
        abort(404)
    db.session.delete(key)
    db.session.commit()
    flash("Key permanently deleted.", "success")
    return redirect(url_for("admin.keys"))


@admin_bp.route("/products")
@admin_required
def products():
    products_list = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin/products.html", products=products_list)


@admin_bp.route("/products/<int:product_id>/tiers")
@admin_required
def product_tiers(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    tiers = PricingTier.query.filter_by(product_id=product.id).order_by(PricingTier.duration_days).all()
    return render_template("admin/product_tiers.html", product=product, tiers=tiers)


@admin_bp.route("/products/<int:product_id>/tiers/add", methods=["POST"])
@admin_required
def add_tier(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    label = request.form.get("label", "").strip()
    duration = request.form.get("duration_days", 0, type=int)
    price = request.form.get("price_pounds", 0, type=float)
    if not label or duration <= 0 or price <= 0:
        flash("All fields are required and must be positive.", "error")
        return redirect(url_for("admin.product_tiers", product_id=product.id))
    tier = PricingTier(
        product_id=product.id,
        label=label,
        duration_days=duration,
        price_pence=int(price * 100),
    )
    db.session.add(tier)
    db.session.commit()
    flash(f"Tier '{label}' added.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


@admin_bp.route("/tiers/<int:tier_id>/edit", methods=["POST"])
@admin_required
def edit_tier(tier_id):
    tier = db.session.get(PricingTier, tier_id)
    if not tier:
        abort(404)
    tier.label = request.form.get("label", tier.label).strip()
    tier.duration_days = request.form.get("duration_days", tier.duration_days, type=int)
    price = request.form.get("price_pounds", type=float)
    if price:
        tier.price_pence = int(price * 100)
    db.session.commit()
    flash("Tier updated.", "success")
    return redirect(url_for("admin.product_tiers", product_id=tier.product_id))


@admin_bp.route("/tiers/<int:tier_id>/delete", methods=["POST"])
@admin_required
def delete_tier(tier_id):
    tier = db.session.get(PricingTier, tier_id)
    if not tier:
        abort(404)
    pid = tier.product_id
    db.session.delete(tier)
    db.session.commit()
    flash("Tier deleted.", "success")
    return redirect(url_for("admin.product_tiers", product_id=pid))


@admin_bp.route("/orders")
@admin_required
def orders():
    status_filter = request.args.get("status", "")
    page = request.args.get("page", 1, type=int)
    query = Order.query.order_by(Order.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders_list = query.paginate(page=page, per_page=30, error_out=False)
    return render_template("admin/orders.html", orders=orders_list, status_filter=status_filter)


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        fields = {
            "stripe_secret_key": "Stripe Secret Key",
            "stripe_publishable_key": "Stripe Publishable Key",
            "stripe_webhook_secret": "Stripe Webhook Secret",
            "site_url": "Site URL",
        }
        for key, label in fields.items():
            val = request.form.get(key, "").strip()
            if val:
                Setting.set(key, val)
                flash(f"{label} saved.", "success")
        return redirect(url_for("admin.settings"))

    cfg = get_stripe_config()
    return render_template("admin/settings.html",
        stripe_secret=cfg["secret_key"],
        stripe_publishable=cfg["publishable_key"],
        stripe_webhook=cfg["webhook_secret"],
        site_url=cfg["site_url"])
