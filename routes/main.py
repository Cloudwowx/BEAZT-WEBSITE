from pathlib import Path

from flask import Blueprint, render_template, abort, current_app
from flask_login import login_required, current_user
from models import db, Product, Key, PricingTier
from config import get_loader_config

main_bp = Blueprint("main", __name__)


def get_product_features(slug):
    feature_sets = {
        "rust-external-private": {
            "label": "Rust External - BeaZt Legit",
            "items": [
                "Legit ESP suite",
                "Debug camera",
                "Player and resource overlays",
                "Distance and visibility tools",
                "Legit-focused presets",
                "Private build updates",
                "Discord setup support",
            ],
        },
    }
    default_set = {
        "label": "Game Access",
        "items": [
            "Core external toolkit",
            "Visualization modules",
            "Update maintenance",
            "Private support channel",
        ],
    }
    return feature_sets.get(slug, default_set)


def _get_product_features_from_db(product):
    items = []
    if product and product.features_text:
        items = [line.strip() for line in product.features_text.splitlines() if line.strip()]
    if not items:
        items = [
            "Core external toolkit",
            "Visualization modules",
            "Update maintenance",
            "Private support channel",
        ]
    return {
        "label": product.name if product else "Features",
        "items": items,
    }


def _get_chairfbi_cheat_status(product):
    if not product or not product.chairfbi_cheat_id:
        return None
    try:
        from config import get_chairfbi_config
        cfg = get_chairfbi_config()
        if not cfg.get("api_token"):
            return None
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=cfg["api_token"], base_url=cfg.get("api_base"))
        cheats = cf.get_cheats()
        for c in cheats:
            cid = str(c.get("id", ""))
            cname = c.get("name", "")
            if cid == product.chairfbi_cheat_id or cname == product.chairfbi_cheat_id:
                return "online" if c.get("active") else "offline"
    except Exception:
        pass
    return None


def _get_product_gallery(slug, fallback_image=None):
    gallery_dir = Path(current_app.root_path) / "static" / "images" / "products" / slug
    images = []
    if gallery_dir.exists() and gallery_dir.is_dir():
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
        for file_path in sorted(gallery_dir.iterdir()):
            if file_path.suffix.lower() in allowed:
                images.append(f"/static/images/products/{slug}/{file_path.name}")

    if not images and fallback_image:
        images.append(fallback_image)

    return images


@main_bp.route("/")
def index():
    product = Product.query.filter_by(slug="rust-external-private").first()
    all_products = Product.query.order_by(Product.created_at.asc()).all()
    cheat_statuses_home = {}
    for p in all_products:
        cheat_statuses_home[p.id] = _get_chairfbi_cheat_status(p)
    tiers = []
    product_features = {"label": "Game Access", "items": []}
    cheat_status = None
    if product:
        tiers = (
            PricingTier.query
            .filter_by(product_id=product.id)
            .order_by(PricingTier.duration_days)
            .all()
        )
        product_features = _get_product_features_from_db(product)
        cheat_status = _get_chairfbi_cheat_status(product)
    return render_template("index.html", product=product, tiers=tiers, product_features=product_features, cheat_status=cheat_status, all_products=all_products, cheat_statuses_home=cheat_statuses_home)


@main_bp.route("/cheats")
def cheats():
    products = Product.query.order_by(Product.created_at.asc()).all()
    cheat_statuses = {}
    product_tiers = {}
    for p in products:
        status = _get_chairfbi_cheat_status(p)
        cheat_statuses[p.id] = status
        product_tiers[p.id] = (
            PricingTier.query
            .filter_by(product_id=p.id)
            .order_by(PricingTier.duration_days)
            .all()
        )
    return render_template("cheats.html", products=products, cheat_statuses=cheat_statuses, product_tiers=product_tiers)


@main_bp.route("/product/<slug>")
def product_detail(slug):
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)
    product_features = _get_product_features_from_db(product)
    cheat_status = _get_chairfbi_cheat_status(product)
    tiers = (
        PricingTier.query
        .filter_by(product_id=product.id)
        .order_by(PricingTier.duration_days)
        .all()
    )
    selected_tier = next((tier for tier in tiers if tier.duration_days == 30), tiers[0] if tiers else None)
    gallery_images = _get_product_gallery(product.slug, product.image_url)
    return render_template(
        "product.html",
        product=product,
        tiers=tiers,
        selected_tier=selected_tier,
        gallery_images=gallery_images,
        product_features=product_features,
        cheat_status=cheat_status,
    )


@main_bp.route("/plan/<int:tier_id>")
def plan_detail(tier_id):
    selected_tier = db.session.get(PricingTier, tier_id)
    if not selected_tier:
        abort(404)

    product = Product.query.filter_by(id=selected_tier.product_id).first()
    if not product:
        abort(404)

    tiers = (
        PricingTier.query
        .filter_by(product_id=product.id)
        .order_by(PricingTier.duration_days)
        .all()
    )
    product_features = _get_product_features_from_db(product)
    cheat_status = _get_chairfbi_cheat_status(product)
    gallery_images = _get_product_gallery(product.slug, product.image_url)

    return render_template(
        "product.html",
        product=product,
        tiers=tiers,
        selected_tier=selected_tier,
        gallery_images=gallery_images,
        product_features=product_features,
        cheat_status=cheat_status,
    )


@main_bp.route("/loader")
def loader():
    loader = get_loader_config()
    return render_template("loader.html", loader_token=loader["loader_token"], loader_url=loader["loader_url"])


@main_bp.route("/feedback")
def feedback():
    return render_template("feedback.html")


@main_bp.route("/terms-of-service")
def terms():
    return render_template("terms.html")


@main_bp.route("/faq")
def faq():
    return render_template("faq.html")


@main_bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@main_bp.route("/my-keys")
@login_required
def my_keys():
    keys = (
        Key.query
        .filter_by(user_id=current_user.id)
        .order_by(Key.created_at.desc())
        .all()
    )
    loader = get_loader_config()
    return render_template("keys.html", keys=keys, loader_token=loader["loader_token"], loader_url=loader["loader_url"])
