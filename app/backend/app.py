"""Flask Application Factory for AU Accounting SaaS."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, g, jsonify, send_from_directory
from flask_cors import CORS

from .db import ApiError, init_db
from .demo_seed import seed_demo_company_au
from .routes.accounting_routes import acc_bp
from .routes.core_routes import core_bp
from .seed import bootstrap_initial_orgs

APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = APP_DIR / "data" / "accounting.db"
FRONTEND_DIST_DIR = APP_DIR / "frontend" / "dist"


def create_app(db_path: str | Path | None = None, bootstrap: bool = True) -> Flask:
    resolved_db = db_path or os.environ.get("ACCOUNTING_DB_PATH") or DEFAULT_DB_PATH
    # For test isolation with :memory:, create shared connection once per app instance
    shared_conn = init_db(resolved_db)
    if bootstrap:
        bootstrap_initial_orgs(shared_conn)
        seed_demo_company_au(shared_conn, replace_existing=False)
    if str(resolved_db) != ":memory:":
        shared_conn.close()

    static_folder = str(FRONTEND_DIST_DIR) if FRONTEND_DIST_DIR.exists() else None
    app = Flask(__name__, static_folder=static_folder, static_url_path="")
    CORS(app)
    app.config["DB_PATH"] = str(resolved_db)

    @app.before_request
    def attach_db():
        if str(resolved_db) == ":memory:":
            g.db = shared_conn
        else:
            from .db import get_connection
            g.db = get_connection(resolved_db)

    @app.teardown_request
    def close_db(exc):
        conn = getattr(g, "db", None)
        if conn is not None and str(resolved_db) != ":memory:":
            conn.close()

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify({"error": {"code": err.code, "message": err.message, "details": err.details}}), err.status_code

    app.register_blueprint(core_bp)
    app.register_blueprint(acc_bp)

    @app.get("/")
    @app.get("/<path:subpath>")
    def serve_spa(subpath: str = ""):
        if subpath.startswith("api/"):
            return jsonify({"error": {"code": "NOT_FOUND", "message": "API endpoint not found"}}), 404
        if FRONTEND_DIST_DIR.exists():
            candidate = FRONTEND_DIST_DIR / subpath
            if subpath and candidate.is_file():
                return send_from_directory(str(FRONTEND_DIST_DIR), subpath)
            return send_from_directory(str(FRONTEND_DIST_DIR), "index.html")
        return jsonify({"message": "AU Accounting SaaS API running. Build frontend in app/frontend or run Vite dev server."})

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=False)
