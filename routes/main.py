from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from models import Product, Key, PricingTier

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    product = Product.query.filter_by(slug="rust-external-private").first()
    tiers = []
    if product:
        tiers = (
            PricingTier.query
            .filter_by(product_id=product.id)
            .order_by(PricingTier.duration_days)
            .all()
        )
    return render_template("index.html", product=product, tiers=tiers)


@main_bp.route("/product/<slug>")
def product_detail(slug):
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)
    tiers = (
        PricingTier.query
        .filter_by(product_id=product.id)
        .order_by(PricingTier.duration_days)
        .all()
    )
    return render_template("product.html", product=product, tiers=tiers)


@main_bp.route("/feedback")
def feedback():
    return render_template("feedback.html")


@main_bp.route("/terms-of-service")
def terms():
    return render_template("terms.html")


@main_bp.route("/my-keys")
@login_required
def my_keys():
    keys = (
        Key.query
        .filter_by(user_id=current_user.id)
        .order_by(Key.created_at.desc())
        .all()
    )
    return render_template("keys.html", keys=keys)
