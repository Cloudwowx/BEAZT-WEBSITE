from functools import wraps
import secrets
import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from models import db, User, Product, PricingTier, Order, Key, Setting
from config import get_stripe_config, get_chairfbi_config, get_loader_config

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
            balance_data = cf.get_balance()
            if isinstance(balance_data, dict):
                cf_balance = balance_data.get("balance")
            else:
                cf_balance = balance_data
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

    product = Product(
        name=name,
        slug=slug,
        description=description or None,
        image_url=image_url or None,
        is_private=True,
        key_source=key_source,
        chairfbi_cheat_id=chairfbi_cheat_id or None,
    )
    db.session.add(product)
    db.session.commit()
    flash(f"Product '{name}' created.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


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
        db.session.commit()
        flash("Product settings updated.", "success")
        return redirect(url_for("admin.product_tiers", product_id=product.id))

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
            "site_url": "Site URL",
            "chairfbi_api_token": "ChairFBI API Token",
            "chairfbi_api_base": "ChairFBI API Base URL",
            "chairfbi_rust_cheat_id": "ChairFBI Rust Cheat ID",
            "loader_token": "Loader Token",
            "loader_url": "Loader Download URL",
        }
        for key, label in fields.items():
            val = request.form.get(key, "").strip()
            if val:
                Setting.set(key, val)
                flash(f"{label} saved.", "success")
        return redirect(url_for("admin.settings"))

    cfg = get_stripe_config()
    cf_cfg = get_chairfbi_config()
    loader_cfg = get_loader_config()
    return render_template("admin/settings.html",
        stripe_secret=cfg["secret_key"],
        stripe_publishable=cfg["publishable_key"],
        stripe_webhook=cfg["webhook_secret"],
        site_url=cfg["site_url"],
        chairfbi_api_token=cf_cfg["api_token"],
        chairfbi_api_base=cf_cfg["api_base"],
        chairfbi_rust_cheat_id=cf_cfg["rust_cheat_id"],
        loader_token=loader_cfg["loader_token"],
        loader_url=loader_cfg["loader_url"])


@admin_bp.route("/chairfbi")
@admin_required
def chairfbi_dashboard():
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.se")

    balance = None
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
                balance_data = cf.get_balance()
                balance = balance_data.get("balance") if isinstance(balance_data, dict) else balance_data
            except Exception as e:
                balance_error = str(e)

            try:
                cheats_data = cf.get_cheats()
                cheats = cheats_data if isinstance(cheats_data, list) else []
            except Exception:
                pass

            try:
                keys_data = cf.list_keys(per_page=20)
                recent_cf_keys = keys_data.get("data", []) if isinstance(keys_data, dict) else []
            except Exception:
                pass
        except Exception as e:
            chairfbi_error = str(e)

    products = Product.query.order_by(Product.name).all()
    local_cf_keys = Key.query.filter(Key.chairfbi_key_id.isnot(None)).order_by(Key.created_at.desc()).limit(30).all()

    return render_template(
        "admin/chairfbi.html",
        balance=balance,
        balance_error=balance_error,
        cheats=cheats,
        recent_cf_keys=recent_cf_keys,
        chairfbi_error=chairfbi_error,
        products=products,
        local_cf_keys=local_cf_keys,
    )


@admin_bp.route("/chairfbi/import-all", methods=["POST"])
@admin_required
def chairfbi_import_all():
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.se")

    if not api_token:
        flash("ChairFBI API token not configured.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        cheats_data = cf.get_cheats()
        cheats = cheats_data if isinstance(cheats_data, list) else []

        created = 0
        skipped = 0
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
                skipped += 1
                continue

            product = Product(
                name=cheat_name,
                slug=slug,
                description=None,
                key_source="chairfbi",
                chairfbi_cheat_id=cheat_id,
                is_private=True,
            )
            db.session.add(product)
            created += 1

        db.session.commit()
        flash(f"Imported {created} new cheat(s) from ChairFBI. {skipped} already exist.", "success")
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
    api_base = cfg.get("api_base", "https://access.chairfbi.se")

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
    api_base = cfg.get("api_base", "https://access.chairfbi.se")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        resp = cf._request("POST", f"/keys/{key.chairfbi_key_id}/hwid-reset")
        if resp.status_code in (200, 204):
            flash("HWID reset successful.", "success")
        else:
            flash(f"HWID reset failed: {resp.text}", "error")
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
    api_base = cfg.get("api_base", "https://access.chairfbi.se")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        resp = cf._request("POST", f"/keys/{key.chairfbi_key_id}/vouche")
        if resp.status_code in (200, 204):
            flash("Vouche (6 hours) added successfully.", "success")
        else:
            flash(f"Vouche failed: {resp.text}", "error")
    except Exception as e:
        flash(f"Vouche failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))
