import hashlib
import functools
from flask import request, jsonify, session, redirect, url_for, render_template, Blueprint
from config import APP_PASSWORD

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if APP_PASSWORD and not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login", methods=["GET"])
def login_page():
    if not APP_PASSWORD or session.get("authenticated"):
        return redirect(url_for("index"))
    return render_template("login.html")


@auth_bp.route("/api/login", methods=["POST"])
def login():
    if not APP_PASSWORD:
        return jsonify({"error": "Auth not configured"}), 400
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(APP_PASSWORD.encode()).hexdigest():
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"status": "ok"})
    return jsonify({"error": "Wrong password"}), 403
