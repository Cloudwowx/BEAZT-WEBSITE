from pathlib import Path
import io
import json

from flask import Blueprint, render_template, abort, current_app, Response, redirect, request, url_for
from flask_login import login_required, current_user
from models import db, Product, Key, PricingTier
from config import get_loader_config, get_discord_config

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
            "Core external toolkit with visual overlays",
            "Regular update maintenance included",
            "Private Discord support channel",
            "Configure features in Admin -> Tiers -> Product Content",
        ]
    return {
        "label": product.name if product else "Features",
        "items": items,
    }


@main_bp.route("/cheat-image/<slug>")
def cheat_image(slug):
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)

    if product.image_url:
        from flask import redirect as _redirect
        return _redirect(product.image_url)

    from PIL import Image, ImageDraw, ImageFont

    is_private = product.visibility == "private"
    accent = (30, 58, 95) if is_private else (212, 212, 216)
    accent_dark = (21, 42, 68) if is_private else (100, 100, 110)

    width, height = 600, 340
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / height
        r = int(9 + ratio * 10)
        g = int(11 + ratio * 18)
        b = int(27 + ratio * 22)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    for i in range(3):
        cx = int(width * (0.25 + i * 0.25))
        cy = int(height * (0.4 + i * 0.15))
        r_max = int(width * 0.42)
        for rad in range(r_max, 0, -1):
            alpha = int(max(0, 18 - (rad / r_max) * 18))
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(accent[0], accent[1], accent[2], alpha))

    for i in range(40):
        x0 = i * (width // 40)
        x1 = x0 + (width // 80)
        draw.rectangle([x0, 0, x1, height], fill=(accent[0], accent[1], accent[2], 3))

    label = "BEAZT PRIVATE" if is_private else "LICENSE"
    try:
        font_label = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font_label = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font_label)
    lw = bbox[2] - bbox[0]
    label_x = (width - lw) // 2
    draw.rectangle([label_x - 14, 132, label_x + lw + 14, 156], fill=(accent[0], accent[1], accent[2], 40))
    draw.text((label_x, 134), label, fill=accent, font=font_label)

    name = product.name
    try:
        font_name = ImageFont.truetype("impact.ttf", 36)
    except Exception:
        try:
            font_name = ImageFont.truetype("arialbd.ttf", 34)
        except Exception:
            font_name = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), name, font=font_name)
    tw = bbox[2] - bbox[0]
    if tw > width - 40:
        try:
            font_name = ImageFont.truetype("impact.ttf", 28)
        except Exception:
            font_name = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), name, font=font_name)
        tw = bbox[2] - bbox[0]
    tx = (width - tw) // 2
    draw.text((tx + 2, 162), name, fill=(0, 0, 0, 120), font=font_name)
    draw.text((tx, 160), name, fill=(255, 255, 255), font=font_name)

    try:
        font_sub = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font_sub = ImageFont.load_default()
    sub_text = "Private Build" if is_private else "Instant Key Delivery"
    bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    sw = bbox[2] - bbox[0]
    draw.text(((width - sw) // 2, 215), sub_text, fill=(180, 180, 200), font=font_sub)

    try:
        font_tag = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font_tag = ImageFont.load_default()
    tier_count = PricingTier.query.filter_by(product_id=product.id).count()
    tag_text = f"{tier_count} PLAN(S) AVAILABLE" if tier_count > 0 else "COMING SOON"
    bbox = draw.textbbox((0, 0), tag_text, font=font_tag)
    tag_w = bbox[2] - bbox[0]
    tag_x = (width - tag_w) // 2
    draw.rectangle([tag_x - 12, 296, tag_x + tag_w + 12, 318], fill=(accent[0], accent[1], accent[2], 30))
    draw.text((tag_x, 298), tag_text, fill=accent, font=font_tag)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


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


def _get_product_gallery(slug, product=None):
    images = []

    if product and product.gallery_images:
        try:
            import json
            vc_images = json.loads(product.gallery_images)
            if isinstance(vc_images, list):
                images.extend(vc_images)
        except (json.JSONDecodeError, TypeError):
            pass

    gallery_dir = Path(current_app.root_path) / "static" / "images" / "products" / slug
    if gallery_dir.exists() and gallery_dir.is_dir():
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
        for file_path in sorted(gallery_dir.iterdir()):
            if file_path.suffix.lower() in allowed:
                images.append(f"/static/images/products/{slug}/{file_path.name}")

    if not images and product and product.image_url:
        images.append(product.image_url)
    elif not images and product is None:
        pass

    return images


@main_bp.route("/")
def index():
    product = Product.query.filter_by(slug="rust-external-private").first()
    all_products = Product.query.order_by(Product.created_at.asc()).all()
    private_products = [p for p in all_products if p.visibility == "private"]
    resold_products = [p for p in all_products if p.visibility != "private"]
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
    discord_cfg = get_discord_config()
    return render_template("index.html", product=product, tiers=tiers, product_features=product_features, cheat_status=cheat_status, all_products=all_products, cheat_statuses_home=cheat_statuses_home, private_products=private_products, resold_products=resold_products, discord_public_url=discord_cfg["public_url"])


@main_bp.route("/cheats")
def cheats():
    products = Product.query.order_by(Product.created_at.asc()).all()
    private_products = [p for p in products if p.visibility == "private"]
    resold_products = [p for p in products if p.visibility != "private"]
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
    return render_template("cheats.html", products=products, cheat_statuses=cheat_statuses, product_tiers=product_tiers, private_products=private_products, resold_products=resold_products)


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
    preselected_id = request.args.get("tier_id", type=int)
    selected_tier = None
    if preselected_id:
        selected_tier = next((t for t in tiers if t.id == preselected_id), None)
    if not selected_tier:
        selected_tier = next((t for t in tiers if t.duration_days == 30), tiers[0] if tiers else None)

    product_features = _get_product_features_from_db(product)
    cheat_status = _get_chairfbi_cheat_status(product)
    gallery_images = _get_product_gallery(product.slug, product=product)

    vc_specs = None
    vc_features = []
    vc_status = None
    vc_system_features = []
    vc_cap_names = {}
    if product.venomcheats_data:
        try:
            vc_data = json.loads(product.venomcheats_data)
            vc_specs = {
                'os': vc_data.get('operatingSystem', ''),
                'cpu': vc_data.get('processor', ''),
                'ac': vc_data.get('antiCheat', ''),
            }
            vc_features = vc_data.get('capabilities', [])
            vc_status = vc_data.get('status', '')
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        from utils.venomcheats import CAPABILITY_NAMES, SYSTEM_FEATURES
        vc_cap_names = CAPABILITY_NAMES
        vc_system_features = SYSTEM_FEATURES
    except ImportError:
        pass

    variants = []
    for t in tiers:
        variants.append({
            "id": t.id,
            "label": t.label,
            "duration_days": t.duration_days,
            "price_pence": t.price_pence,
            "price_pounds": t.price_pounds,
            "billing_type": t.billing_type,
            "subscription_link": t.ivno_subscription_link or "",
        })

    return render_template(
        "product.html",
        product=product,
        tiers=tiers,
        selected_tier=selected_tier,
        gallery_images=gallery_images,
        product_features=product_features,
        cheat_status=cheat_status,
        variants=variants,
        vc_specs=vc_specs,
        vc_features=vc_features,
        vc_status=vc_status,
        vc_cap_names=vc_cap_names,
        vc_system_features=vc_system_features,
    )


@main_bp.route("/plan/<int:tier_id>")
def plan_detail(tier_id):
    tier = db.session.get(PricingTier, tier_id)
    if not tier:
        abort(404)
    product = Product.query.filter_by(id=tier.product_id).first()
    if not product:
        abort(404)
    return redirect(url_for("main.product_detail", slug=product.slug, tier_id=tier_id))


@main_bp.route("/loader")
def loader():
    loader = get_loader_config()
    return render_template("loader.html", 
        loader_token=loader["loader_token"],
        loader_public_url=loader.get("loader_public_url", loader.get("loader_url", "")))


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


@main_bp.route("/health/products")
def health_products():
    from models import Product
    products = Product.query.all()
    rows = []
    for p in products:
        rows.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "visibility": p.visibility,
            "key_source": p.key_source,
            "is_private": p.is_private,
            "has_vc": bool(p.venomcheats_slug),
        })
    import os as _os
    return {
        "count": len(rows),
        "products": rows,
        "vercel": _os.environ.get("VERCEL") == "1",
        "db_path": current_app.config.get("SQLALCHEMY_DATABASE_URI", "")[:80],
    }


@main_bp.route("/health/kv")
def health_kv():
    import os as _os
    keys_found = {}
    for k in sorted(_os.environ.keys()):
        kl = k.lower()
        if "kv" in kl or "redis" in kl or "upstash" in kl:
            keys_found[k] = _os.environ[k][:20] + "..."
    return {
        "kv_available": bool(_os.environ.get("KV_REST_API_URL") or _os.environ.get("KV_URL")),
        "kv_keys_found": keys_found,
        "all_env_prefixes": sorted(set(k.split("_")[0] for k in _os.environ.keys())),
    }


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
    discord_cfg = get_discord_config()
    has_private = any(k.product and k.product.visibility == "private" and k.is_active for k in keys)
    return render_template("keys.html", keys=keys, 
        loader_token=loader["loader_token"],
        loader_public_url=loader.get("loader_public_url", loader.get("loader_url", "")),
        loader_private_url=loader.get("loader_private_url", ""),
        discord_public_url=discord_cfg["public_url"],
        discord_private_url=discord_cfg["private_url"],
        has_private=has_private)
