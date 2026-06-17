import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(__file__))

try:
    from app import app as application
except Exception:
    err_file = os.path.join(os.path.dirname(__file__), "passenger_error.log")
    with open(err_file, "w") as f:
        f.write("IMPORT FAILED:\n")
        traceback.print_exc(file=f)
    # Try minimal app
    from flask import Flask
    application = Flask(__name__)

    @application.route("/")
    def index():
        with open(err_file) as f:
            return "<pre>" + f.read() + "</pre>"
