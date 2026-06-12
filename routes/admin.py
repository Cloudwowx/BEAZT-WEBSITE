from functools import wraps
import secrets
import re
import json
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app, Response
from flask_login import login_required, current_user
from models import db, User, Product, PricingTier, Order, Key, Setting
from config import get_stripe_config, get_chairfbi_config, get_loader_config, get_discord_config

admin_bp = Blueprint("admin", __name__)
logger = logging.getLogger(__name__)


def _enrich_product_from_venomcheats(product, vc_products=None):
    """Auto-enrich a Product with VenomCheats data if name matches.

    Args:
        product: Product model instance to enrich.
        vc_products: Optional pre-fetched dict {slug: product_data} or list of product dicts.
                     If None, fetches from VenomCheats homepage.
    """
    try:
        from utils.venomcheats import (
            match_chairfbi_to_venom,
            get_all_products,
            find_product_by_slug,
            build_features_text,
            build_description,
            get_primary_image_url,
            download_product_media,
        )

        slug = product.venomcheats_slug or match_chairfbi_to_venom(product.name)
        if not slug:
            return False

        if vc_products is None:
            vc_products = get_all_products()
        if not vc_products:
            return False

        if isinstance(vc_products, dict):
            vc_data = vc_products.get(slug)
        else:
            vc_data = find_product_by_slug(vc_products, slug)
        if not vc_data:
            return False

        product.venomcheats_slug = slug
        product.venomcheats_data = json.dumps(vc_data, ensure_ascii=False)
        product.last_synced_at = datetime.utcnow()
        product.features_text = build_features_text(vc_data)
        product.description = build_description(vc_data)
        product.image_url = get_primary_image_url(vc_data)

        static_dir = os.path.join(current_app.root_path, "static")
        gallery_paths = download_product_media(vc_data, static_dir)
        if gallery_paths:
            product.gallery_images = json.dumps(gallery_paths)

        db.session.commit()
        _backup_products_safe()
        logger.info("Enriched product '%s' from VenomCheats (slug=%s)", product.name, slug)
        return True
    except Exception as e:
        logger.warning("VenomCheats enrichment failed for '%s': %s", product.name, e)
        return False


def _backup_products_safe():
    try:
        from utils.kv_store import backup_products, backup_users
        ok_p = backup_products()
        ok_u = backup_users()
        return ok_p and ok_u
    except Exception as e:
        logger.error("Product backup to KV failed: %s", e)
        return False


_FALLBACK_TIERS = [
    ("1 Day", 1, 4.99),
    ("3 Days", 3, 9.99),
    ("7 Days", 7, 16.99),
    ("30 Days", 30, 49.99),
]

_PRIVATE_TIERS = [
    ("1 Month", 30, 49.99, True),
    ("12 Months", 365, 399.99, True),
]


def _get_vc_slug(product):
    if product.venomcheats_slug:
        return product.venomcheats_slug
    try:
        from utils.venomcheats import match_chairfbi_to_venom
        return match_chairfbi_to_venom(product.name)
    except Exception:
        return None


def _sync_product_tiers(product):
    if PricingTier.query.filter_by(product_id=product.id).first():
        return

    if product.visibility == "private":
        for label, days, price, sub in _PRIVATE_TIERS:
            db.session.add(PricingTier(
                product_id=product.id,
                label=label,
                duration_days=days,
                price_pence=int(price * 100),
                is_subscription=True,
            ))
        db.session.commit()
        return

    tiers_data = None
    slug = _get_vc_slug(product)
    if slug:
        try:
            from utils.venomcheats import fetch_product_pricing
            tiers_data = fetch_product_pricing(slug)
        except Exception:
            pass

    if not tiers_data:
        tiers_data = _FALLBACK_TIERS

    for label, days, price in tiers_data:
        db.session.add(PricingTier(
            product_id=product.id,
            label=label,
            duration_days=days,
            price_pence=int(price * 100),
        ))
    db.session.commit()


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
    awaiting_keys = Order.query.filter_by(status="awaiting_keys").count()
    total_products = Product.query.count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_keys = Key.query.order_by(Key.created_at.desc()).limit(5).all()

    revenue_pence = 0
    completed = Order.query.filter_by(status="completed").all()
    for o in completed:
        if o.tier:
            revenue_pence += o.tier.price_pence

    cf_balance = None
    cf_balance_error = None
    cf_config = get_chairfbi_config()
    if cf_config.get("api_token"):
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=cf_config["api_token"], base_url=cf_config.get("api_base"))
            cf_balance = cf.get_balance()
        except Exception as e:
            cf_balance_error = str(e)

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_keys=total_keys,
        active_keys=active_keys,
        total_orders=total_orders,
        completed_orders=completed_orders,
        awaiting_keys=awaiting_keys,
        total_products=total_products,
        revenue_pounds=revenue_pence / 100,
        recent_users=recent_users,
        recent_keys=recent_keys,
        cf_balance=cf_balance,
        cf_balance_error=cf_balance_error,
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
    key_filter = request.args.get("filter", "")
    query = Key.query.order_by(Key.created_at.desc())
    if key_filter == "pool":
        query = query.filter(Key.user_id.is_(None))
    elif key_filter == "active":
        query = query.filter(Key.user_id.isnot(None), Key.is_active == True)
    elif key_filter == "expired":
        query = query.filter(Key.user_id.isnot(None), Key.is_active == False)
    keys_list = query.paginate(page=page, per_page=30, error_out=False)
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


@admin_bp.route("/products/create", methods=["POST"])
@admin_required
def create_product():
    name = request.form.get("name", "").strip()
    slug = request.form.get("slug", "").strip()
    key_source = request.form.get("key_source", "chairfbi").strip()
    chairfbi_cheat_id = request.form.get("chairfbi_cheat_id", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()

    if not name:
        flash("Product name is required.", "error")
        return redirect(url_for("admin.products"))
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if Product.query.filter_by(slug=slug).first():
        flash(f"Slug '{slug}' already exists. Choose a different name.", "error")
        return redirect(url_for("admin.products"))
    if key_source not in ("pool", "chairfbi"):
        flash("Key source must be pool or chairfbi.", "error")
        return redirect(url_for("admin.products"))
    if key_source == "pool":
        chairfbi_cheat_id = None
    visibility_val = request.form.get("visibility", "public").strip()
    if visibility_val not in ("private", "public"):
        visibility_val = "public"

    product = Product(
        name=name,
        slug=slug,
        description=description or None,
        image_url=image_url or None,
        is_private=(visibility_val == "private"),
        key_source=key_source,
        chairfbi_cheat_id=chairfbi_cheat_id or None,
        visibility=visibility_val,
    )
    db.session.add(product)
    db.session.commit()
    _backup_products_safe()
    flash(f"Product '{name}' created.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


@admin_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    Order.query.filter(Order.tier.has(product_id=product.id)).delete(synchronize_session="fetch")
    Key.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
    PricingTier.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
    db.session.delete(product)
    db.session.commit()
    flash(f"Product '{product.name}' and all associated keys/orders deleted.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/bulk-delete", methods=["POST"])
@admin_required
def bulk_delete_products():
    ids = request.form.getlist("product_ids")
    if not ids:
        flash("No products selected.", "error")
        return redirect(url_for("admin.products"))
    count = 0
    for pid in ids:
        product = db.session.get(Product, int(pid))
        if not product:
            continue
        Order.query.filter(Order.tier.has(product_id=product.id)).delete(synchronize_session="fetch")
        Key.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
        PricingTier.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
        db.session.delete(product)
        count += 1
    db.session.commit()
    _backup_products_safe()
    flash(f"{count} product(s) deleted.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/export")
@admin_required
def export_products():
    products = Product.query.order_by(Product.created_at.asc()).all()
    data = []
    for p in products:
        tiers = []
        for t in PricingTier.query.filter_by(product_id=p.id).order_by(PricingTier.duration_days).all():
            tiers.append({
                "label": t.label,
                "duration_days": t.duration_days,
                "price_pence": t.price_pence,
            })
        data.append({
            "name": p.name,
            "slug": p.slug,
            "description": p.description,
            "features_text": p.features_text,
            "buyer_notes": p.buyer_notes,
            "image_url": p.image_url,
            "key_source": p.key_source,
            "visibility": p.visibility,
            "chairfbi_cheat_id": p.chairfbi_cheat_id,
            "is_private": p.is_private,
            "tiers": tiers,
        })
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=beazt_products.json"}
    )


@admin_bp.route("/products/import", methods=["POST"])
@admin_required
def import_products():
    file = request.files.get("products_file")
    if not file or file.filename == "":
        flash("Please select a JSON file to import.", "error")
        return redirect(url_for("admin.products"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        flash(f"Invalid JSON file: {e}", "error")
        return redirect(url_for("admin.products"))

    if not isinstance(data, list):
        flash("JSON must be an array of products.", "error")
        return redirect(url_for("admin.products"))

    created = 0
    updated = 0
    for entry in data:
        slug = entry.get("slug", "").strip()
        if not slug:
            continue

        product = Product.query.filter_by(slug=slug).first()
        if not product:
            product = Product(slug=slug)
            db.session.add(product)
            created += 1
        else:
            updated += 1

        product.name = entry.get("name", product.name or slug)
        product.description = entry.get("description") or None
        product.features_text = entry.get("features_text") or None
        product.buyer_notes = entry.get("buyer_notes") or None
        product.image_url = entry.get("image_url") or None
        product.key_source = entry.get("key_source", "chairfbi")
        product.visibility = entry.get("visibility", "public")
        product.chairfbi_cheat_id = entry.get("chairfbi_cheat_id") or None
        product.is_private = entry.get("is_private", True)
        db.session.flush()

        tiers_data = entry.get("tiers", [])
        PricingTier.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
        for t_entry in tiers_data:
            tier = PricingTier(
                product_id=product.id,
                label=t_entry.get("label", "Untitled"),
                duration_days=int(t_entry.get("duration_days", 1)),
                price_pence=int(t_entry.get("price_pence", 0)),
            )
            db.session.add(tier)

    db.session.commit()
    flash(f"Import complete: {created} created, {updated} updated.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/<int:product_id>/tiers", methods=["GET", "POST"])
@admin_required
def product_tiers(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)

    if request.method == "POST":
        cheat_id = request.form.get("chairfbi_cheat_id", "").strip()
        key_source_val = request.form.get("key_source", "").strip()
        if key_source_val in ("pool", "chairfbi"):
            product.key_source = key_source_val
            if key_source_val == "pool":
                product.chairfbi_cheat_id = None
                cheat_id = None
        product.chairfbi_cheat_id = cheat_id if cheat_id else None
        visibility_val = request.form.get("visibility", "").strip()
        if visibility_val in ("private", "public"):
            product.visibility = visibility_val
        if "name" in request.form:
            new_name = request.form.get("name", "").strip()
            if new_name and new_name != product.name:
                product.name = new_name
        if "slug" in request.form:
            new_slug = request.form.get("slug", "").strip()
            if new_slug and new_slug != product.slug:
                if not Product.query.filter(Product.slug == new_slug, Product.id != product.id).first():
                    product.slug = new_slug
                else:
                    flash("Slug already taken. Keep the current one.", "error")
                    return redirect(url_for("admin.product_tiers", product_id=product.id))
        if "description" in request.form:
            product.description = request.form.get("description", "").strip() or None
        if "features_text" in request.form:
            product.features_text = request.form.get("features_text", "").strip() or None
        if "buyer_notes" in request.form:
            product.buyer_notes = request.form.get("buyer_notes", "").strip() or None

        image_file = request.files.get("image_file")
        if image_file and image_file.filename:
            ext = os.path.splitext(image_file.filename)[1].lower()
            if ext in (".png", ".jpg", ".jpeg"):
                file_bytes = image_file.read()
                saved = False
                try:
                    upload_dir = os.path.join(current_app.root_path, "static", "images", "products", product.slug)
                    os.makedirs(upload_dir, exist_ok=True)
                    path = os.path.join(upload_dir, f"banner{ext}")
                    with open(path, "wb") as f:
                        f.write(file_bytes)
                    product.image_url = f"/static/images/products/{product.slug}/banner{ext}"
                    saved = True
                except OSError:
                    pass
                if not saved:
                    import base64
                    imgbb_key = os.environ.get("IMGBB_API_KEY", "")
                    if imgbb_key:
                        try:
                            import requests as _req
                            resp = _req.post(
                                "https://api.imgbb.com/1/upload",
                                data={"key": imgbb_key, "image": base64.b64encode(file_bytes).decode()},
                                timeout=15,
                            )
                            data = resp.json()
                            if data.get("success"):
                                product.image_url = data["data"]["url"]
                            else:
                                flash("imgbb upload failed. Use the URL field instead.", "error")
                        except Exception:
                            flash("Banner upload failed. Use the URL field instead.", "error")
                    else:
                        flash("Banner upload unavailable. Set IMGBB_API_KEY or use the URL field.", "warn")
            else:
                flash("Only PNG and JPEG files are accepted.", "error")
                return redirect(url_for("admin.product_tiers", product_id=product.id))
        elif "image_url" in request.form:
            image_url_val = request.form.get("image_url", "").strip()
            product.image_url = image_url_val if image_url_val else None

        # Gallery image manager
        gallery = []
        if product.gallery_images:
            try:
                gallery = json.loads(product.gallery_images)
            except (json.JSONDecodeError, TypeError):
                pass

        delete_idx = request.form.get("delete_gallery_image", type=int)
        if delete_idx is not None and 0 <= delete_idx < len(gallery):
            gallery.pop(delete_idx)

        add_url = request.form.get("add_gallery_url", "").strip()
        if add_url:
            gallery.append(add_url)

        gallery_file = request.files.get("gallery_upload")
        if gallery_file and gallery_file.filename:
            ext = os.path.splitext(gallery_file.filename)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".webp"):
                file_bytes = gallery_file.read()
                # Try local save first
                saved = False
                try:
                    upload_dir = os.path.join(current_app.root_path, "static", "images", "products", product.slug)
                    os.makedirs(upload_dir, exist_ok=True)
                    count = len([f for f in os.listdir(upload_dir) if f.startswith("gallery_")])
                    fname = f"gallery_{count}{ext}"
                    with open(os.path.join(upload_dir, fname), "wb") as f:
                        f.write(file_bytes)
                    gallery.append(f"/static/images/products/{product.slug}/{fname}")
                    saved = True
                except OSError:
                    pass

                # Fallback: upload to imgbb
                if not saved:
                    import base64
                    imgbb_key = os.environ.get("IMGBB_API_KEY", "")
                    if imgbb_key:
                        try:
                            import requests as _req
                            resp = _req.post(
                                "https://api.imgbb.com/1/upload",
                                data={
                                    "key": imgbb_key,
                                    "image": base64.b64encode(file_bytes).decode(),
                                },
                                timeout=15,
                            )
                            data = resp.json()
                            if data.get("success"):
                                gallery.append(data["data"]["url"])
                                flash("Image uploaded via imgbb.", "success")
                            else:
                                flash("imgbb upload failed. Use the URL field instead.", "error")
                        except Exception:
                            flash("Image upload failed. Use the URL field instead.", "error")
                    else:
                        flash("Upload unavailable. Set IMGBB_API_KEY or use the URL field.", "warn")

        product.gallery_images = json.dumps(gallery) if gallery else None

        db.session.commit()
        ok = _backup_products_safe()
        product = db.session.get(Product, product_id)
        if ok:
            flash(f"Product updated — visibility: {product.visibility}, tiers: {product.tiers.count()}", "success")
        else:
            flash(f"Saved locally (KV unavailable). Visibility: {product.visibility}. Link KV and redeploy.", "warn")
        return redirect(url_for("admin.product_tiers", product_id=product.id))

    gallery_imgs = []
    if product.gallery_images:
        try:
            gallery_imgs = json.loads(product.gallery_images)
        except (json.JSONDecodeError, TypeError):
            pass

    tiers = PricingTier.query.filter_by(product_id=product.id).order_by(PricingTier.duration_days).all()
    return render_template("admin/product_tiers.html", product=product, tiers=tiers, gallery_imgs=gallery_imgs)


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
        is_subscription="1" in request.form.getlist("is_subscription"),
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
    tier.is_subscription = "1" in request.form.getlist("is_subscription")
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

    pool_products = Product.query.filter_by(key_source="pool").all()
    pool_product_ids = [p.id for p in pool_products]
    pool_empty = {}
    for pid in pool_product_ids:
        count = Key.query.filter_by(product_id=pid, user_id=None, is_active=False).count()
        pool_empty[pid] = count

    return render_template(
        "admin/orders.html",
        orders=orders_list,
        status_filter=status_filter,
        pool_products=pool_products,
        pool_empty=pool_empty,
    )


@admin_bp.route("/orders/<int:order_id>/fulfill", methods=["POST"])
@admin_required
def fulfill_order(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    if order.status != "awaiting_keys":
        flash("This order is not awaiting keys.", "error")
        return redirect(url_for("admin.orders"))

    tier = order.tier
    product_id = tier.product_id if tier else None
    tier_id = tier.id if tier else None
    duration_days = tier.duration_days if tier else 30
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    pool_key = (
        Key.query
        .filter_by(product_id=product_id, tier_id=tier_id, user_id=None, is_active=False)
        .order_by(Key.created_at.asc())
        .first()
    )
    if not pool_key:
        flash("Still no pool keys available for this product/tier. Upload more keys first.", "error")
        return redirect(url_for("admin.orders", status="awaiting_keys"))

    pool_key.user_id = order.user_id
    pool_key.order_id = order.id
    pool_key.tier_id = tier_id
    pool_key.expires_at = expires_at
    pool_key.assigned_at = datetime.utcnow()
    pool_key.is_active = True
    order.status = "completed"
    db.session.commit()
    flash(f"Order #{order.id} fulfilled with key {pool_key.key_value[:20]}...", "success")
    return redirect(url_for("admin.orders"))


@admin_bp.route("/products/<int:product_id>/keys", methods=["GET", "POST"])
@admin_required
def product_keys(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    tier_id = request.args.get("tier_id", type=int)

    if request.method == "POST":
        action = request.form.get("action", "add")
        if action == "add":
            raw_keys = request.form.get("keys_text", "").strip()
            sel_tier_id = request.form.get("tier_id", type=int)
            if not raw_keys:
                flash("Paste at least one key.", "error")
                return redirect(url_for("admin.product_keys", product_id=product.id, tier_id=sel_tier_id))
            tier = db.session.get(PricingTier, sel_tier_id) if sel_tier_id else None
            if sel_tier_id and not tier:
                flash("Invalid tier selected.", "error")
                return redirect(url_for("admin.product_keys", product_id=product.id))
            lines = [line.strip() for line in raw_keys.splitlines() if line.strip()]
            added = 0
            skipped = 0
            for line in lines:
                existing = Key.query.filter_by(key_value=line).first()
                if existing:
                    skipped += 1
                    continue
                key = Key(
                    user_id=None,
                    product_id=product.id,
                    tier_id=tier.id if tier else None,
                    key_value=line,
                    is_active=False,
                )
                db.session.add(key)
                added += 1
            db.session.commit()
            flash(f"{added} key(s) added to pool. {skipped} duplicate(s) skipped.", "success")
            return redirect(url_for("admin.product_keys", product_id=product.id, tier_id=sel_tier_id))

        elif action == "delete_pool":
            key_ids = request.form.getlist("key_ids")
            if key_ids:
                Key.query.filter(Key.id.in_([int(k) for k in key_ids]), Key.user_id.is_(None)).delete(synchronize_session="fetch")
                db.session.commit()
                flash(f"{len(key_ids)} pool key(s) deleted.", "success")
            return redirect(url_for("admin.product_keys", product_id=product.id, tier_id=tier_id))

    tiers = PricingTier.query.filter_by(product_id=product.id).order_by(PricingTier.duration_days).all()
    pool_query = Key.query.filter_by(product_id=product.id).filter(Key.user_id.is_(None)).order_by(Key.created_at.desc())
    if tier_id:
        pool_query = pool_query.filter_by(tier_id=tier_id)
    pool_keys = pool_query.all()

    pool_stats = {}
    for t in tiers:
        total = Key.query.filter_by(product_id=product.id, tier_id=t.id).count()
        unassigned = Key.query.filter_by(product_id=product.id, tier_id=t.id).filter(Key.user_id.is_(None)).count()
        assigned = Key.query.filter_by(product_id=product.id, tier_id=t.id).filter(Key.user_id.isnot(None)).count()
        pool_stats[t.id] = {"total": total, "available": unassigned, "assigned": assigned}

    return render_template(
        "admin/product_keys.html",
        product=product,
        tiers=tiers,
        pool_keys=pool_keys,
        selected_tier_id=tier_id,
        pool_stats=pool_stats,
    )


@admin_bp.route("/settings/chairfbi-test", methods=["POST"])
@admin_required
def test_chairfbi():
    from utils.chairfbi import ChairFBI

    token = request.form.get("chairfbi_api_token", "").strip()
    base_url = request.form.get("chairfbi_api_base", "").strip()

    if not token:
        flash("Please enter an API token first.", "error")
        return redirect(url_for("admin.settings"))

    cf = ChairFBI(api_token=token, base_url=base_url or None)
    success, result = cf.test_connection()

    if success:
        flash("ChairFBI connection successful.", "success")
    else:
        flash(f"ChairFBI connection failed: {result}", "error")

    return redirect(url_for("admin.settings"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        fields = {
            "stripe_secret_key": "Stripe Secret Key",
            "stripe_publishable_key": "Stripe Publishable Key",
            "stripe_webhook_secret": "Stripe Webhook Secret",
            "stripe_payment_method_domain": "Stripe Payment Method Domain",
            "site_url": "Site URL",
            "chairfbi_api_token": "ChairFBI API Token",
            "chairfbi_api_base": "ChairFBI API Base URL",
            "loader_token": "Loader Token",
            "loader_url": "Loader Download URL",
            "loader_public_url": "Public Loader Download URL",
            "loader_private_url": "Private Loader Download URL",
            "discord_public_url": "Public Discord URL",
            "discord_private_url": "Private Discord URL",
        }
        for key, label in fields.items():
            val = request.form.get(key, "").strip()
            if val:
                Setting.set(key, val)
                flash(f"{label} saved.", "success")
            else:
                row = db.session.execute(db.select(Setting).filter_by(key=key)).scalar_one_or_none()
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash(f"{label} cleared.", "info")
        return redirect(url_for("admin.settings"))

    cfg = get_stripe_config()
    cf_cfg = get_chairfbi_config()
    loader_cfg = get_loader_config()
    discord_cfg = get_discord_config()
    return render_template("admin/settings.html",
        stripe_secret=cfg["secret_key"],
        stripe_publishable=cfg["publishable_key"],
        stripe_webhook=cfg["webhook_secret"],
        site_url=cfg["site_url"],
        stripe_payment_method_domain=cfg.get("payment_method_domain", ""),
        chairfbi_api_token=cf_cfg["api_token"],
        chairfbi_api_base=cf_cfg["api_base"],
        loader_token=loader_cfg["loader_token"],
        loader_url=loader_cfg.get("loader_url", ""),
        loader_public_url=loader_cfg.get("loader_public_url", ""),
        loader_private_url=loader_cfg.get("loader_private_url", ""),
        discord_public_url=discord_cfg.get("public_url", ""),
        discord_private_url=discord_cfg.get("private_url", ""))


@admin_bp.route("/chairfbi")
@admin_required
def chairfbi_dashboard():
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    balance = None
    cf_balance = None
    cheats = []
    recent_cf_keys = []
    chairfbi_error = None
    balance_error = None

    if not api_token:
        chairfbi_error = "ChairFBI API token not configured. Add it in Settings."
    else:
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=api_token, base_url=api_base)

            try:
                cf_balance = cf.get_balance()
                if cf_balance:
                    bal = float(cf_balance)
                    if bal > 500 and bal == int(bal):
                        cf_balance = bal / 10
            except Exception as e:
                balance_error = str(e)

            try:
                cheats_data = cf.get_cheats()
                cheats = cheats_data if isinstance(cheats_data, list) else []
            except Exception:
                pass

            try:
                keys_data = cf.list_keys(per_page=20)
                recent_cf_keys = keys_data.get("data", []) if isinstance(keys_data, dict) else keys_data if isinstance(keys_data, list) else []
            except Exception:
                pass
        except Exception as e:
            chairfbi_error = str(e)

    products = Product.query.order_by(Product.name).all()
    local_cf_keys = Key.query.filter(Key.chairfbi_key_id.isnot(None)).order_by(Key.created_at.desc()).limit(30).all()

    kv_configured = bool(os.environ.get("KV_URL") or os.environ.get("KV_REST_API_URL") or os.environ.get("REDIS_URL"))

    vc_synced_count = Product.query.filter(Product.venomcheats_slug.isnot(None)).count()
    vc_rating = Setting.query.filter_by(key="venomcheats_rating").first()
    vc_rating_data = None
    if vc_rating and vc_rating.value:
        try:
            vc_rating_data = json.loads(vc_rating.value)
        except json.JSONDecodeError:
            pass

    try:
        from utils.sync import get_last_sync_time
        vc_last_sync = get_last_sync_time()
    except Exception:
        vc_last_sync = None

    return render_template(
        "admin/chairfbi.html",
        balance=cf_balance,
        balance_error=balance_error,
        cheats=cheats,
        recent_cf_keys=recent_cf_keys,
        chairfbi_error=chairfbi_error,
        products=products,
        local_cf_keys=local_cf_keys,
        vc_synced_count=vc_synced_count,
        vc_rating=vc_rating_data,
        vc_last_sync=vc_last_sync,
        kv_configured=kv_configured,
        is_vercel=os.environ.get("VERCEL") == "1",
    )


@admin_bp.route("/chairfbi/import-one", methods=["POST"])
@admin_required
def chairfbi_import_one():
    cheat_id = request.form.get("cheat_id", "").strip()
    cheat_name = request.form.get("cheat_name", "").strip()
    if not cheat_id or not cheat_name:
        flash("Missing cheat ID or name.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    slug = re.sub(r"[^a-z0-9]+", "-", cheat_name.lower()).strip("-")
    if not slug:
        slug = f"cf-cheat-{cheat_id}"

    existing = Product.query.filter_by(slug=slug).first()
    if existing:
        if not existing.chairfbi_cheat_id or existing.chairfbi_cheat_id != cheat_id:
            existing.chairfbi_cheat_id = cheat_id
            existing.key_source = "chairfbi"
            db.session.commit()
            flash(f"'{cheat_name}' was already imported — ChairFBI cheat ID updated.", "info")
        else:
            flash(f"'{cheat_name}' already exists as a product.", "info")

        _enrich_product_from_venomcheats(existing)
        return redirect(url_for("admin.product_tiers", product_id=existing.id))

    product = Product(
        name=cheat_name,
        slug=slug,
        key_source="chairfbi",
        chairfbi_cheat_id=cheat_id,
        is_private=False,
    )
    db.session.add(product)
    db.session.commit()
    _backup_products_safe()
    _sync_product_tiers(product)

    enriched = _enrich_product_from_venomcheats(product)
    if enriched:
        flash(f"'{cheat_name}' imported + enriched from VenomCheats. Add pricing tiers to activate.", "success")
    else:
        flash(f"'{cheat_name}' imported. Add pricing tiers to activate.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


@admin_bp.route("/chairfbi/import-all", methods=["POST"])
@admin_required
def chairfbi_import_all():
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    if not api_token:
        flash("ChairFBI API token not configured.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        cheats_data = cf.get_cheats()
        cheats = cheats_data if isinstance(cheats_data, list) else []

        online_only = request.form.get("online_only") == "1"
        if online_only:
            cheats = [c for c in cheats if c.get("active")]

        created = 0
        skipped = 0
        enriched = 0
        for cheat in cheats:
            cheat_id = str(cheat.get("id", ""))
            cheat_name = cheat.get("name", "Unknown Cheat").strip()
            if not cheat_name:
                continue

            slug = re.sub(r"[^a-z0-9]+", "-", cheat_name.lower()).strip("-")
            if not slug:
                slug = f"cf-cheat-{cheat_id}"

            existing = Product.query.filter_by(slug=slug).first()
            if existing:
                if not existing.chairfbi_cheat_id or existing.chairfbi_cheat_id != cheat_id:
                    existing.chairfbi_cheat_id = cheat_id
                    existing.key_source = "chairfbi"
                if _enrich_product_from_venomcheats(existing):
                    enriched += 1
                skipped += 1
                continue

            product = Product(
                name=cheat_name,
                slug=slug,
                description=None,
                key_source="chairfbi",
                chairfbi_cheat_id=cheat_id,
                is_private=False,
            )
            db.session.add(product)
            created += 1

        db.session.commit()
        _backup_products_safe()

        vc_prefetched = None
        try:
            from utils.venomcheats import get_all_products
            vc_prefetched = get_all_products()
        except Exception:
            pass

        for product in Product.query.order_by(Product.id).all():
            _sync_product_tiers(product)
            if vc_prefetched:
                if _enrich_product_from_venomcheats(product, vc_products=vc_prefetched):
                    enriched += 1

        msg = f"Imported {created} new cheat(s) from ChairFBI. {skipped} already exist."
        if enriched:
            msg += f" {enriched} enriched from VenomCheats."
        flash(msg, "success")
    except Exception as e:
        flash(f"ChairFBI import failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/revoke/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_revoke(key_id):
    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        cf.revoke_key(key.chairfbi_key_id)
        key.is_active = False
        db.session.commit()
        flash("ChairFBI key revoked successfully.", "success")
    except Exception as e:
        flash(f"ChairFBI revoke failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/hwid-reset/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_hwid_reset(key_id):
    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        resp = cf.update_keys(keys=[key.chairfbi_key_id], hwid=True)
        if resp.get("errors", 0) == 0:
            flash("HWID reset successful.", "success")
        else:
            flash("HWID reset failed.", "error")
    except Exception as e:
        flash(f"HWID reset failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/vouche/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_vouche(key_id):
    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        resp = cf.update_keys(keys=[key.chairfbi_key_id], vouche=True)
        if resp.get("errors", 0) == 0:
            flash("Vouche (6 hours) added successfully.", "success")
        else:
            flash("Vouche failed.", "error")
    except Exception as e:
        flash(f"Vouche failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/sync-venomcheats", methods=["POST"])
@admin_required
def chairfbi_sync_venomcheats():
    try:
        from utils.venomcheats import sync_all, get_rating

        static_dir = os.path.join(current_app.root_path, "static")
        vc_data = sync_all(static_dir=static_dir)

        if not vc_data:
            flash("No data received from VenomCheats.", "error")
            return redirect(url_for("admin.chairfbi_dashboard"))

        products = Product.query.all()
        updated = 0
        for product in products:
            if _enrich_product_from_venomcheats(product, vc_products=vc_data):
                _sync_product_tiers(product)
                updated += 1

        rating = get_rating()
        if rating:
            existing = Setting.query.filter_by(key="venomcheats_rating").first()
            if existing:
                existing.value = json.dumps(rating)
            else:
                db.session.add(Setting(key="venomcheats_rating", value=json.dumps(rating)))

        db.session.commit()
        _backup_products_safe()
        flash(f"Updated {updated} product(s) from VenomCheats.", "success")
    except Exception as e:
        flash(f"VenomCheats sync failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))
