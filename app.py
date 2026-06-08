import os
from flask import Flask
from config import Config
from models import db, User, seed_products
from flask_login import LoginManager

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"

app = Flask(__name__)
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

with app.app_context():
    db.create_all()
    seed_products()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
