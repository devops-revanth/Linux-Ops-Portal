"""
API v1 routes — thin controllers only.

All database logic lives in queries.py.

Authentication:
  Every endpoint requires:   Authorization: Bearer <API_TOKEN>
  Requests without a valid token receive HTTP 401.

CSRF:
  These endpoints are called by Ansible (machine-to-machine), so they
  are exempt from Flask-WTF's CSRF protection.
"""
import logging

from flask import jsonify, request

from ...extensions import csrf
from ...models.api_token import ApiToken
from . import api_bp
from .queries import upsert_server, validate_inventory_payload

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


# ── Auth helper ───────────────────────────────────────────────────────── #

def _get_bearer_token() -> str | None:
    """Extract the raw token from the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return None


def _authenticate() -> bool:
    """Return True if the request carries a valid active token."""
    token = _get_bearer_token()
    if not token:
        return False
    return ApiToken.validate(token)


# ── Inventory endpoint ────────────────────────────────────────────────── #

@api_bp.route(f"{API_PREFIX}/inventory", methods=["POST"])
@csrf.exempt
def inventory_sync():
    """
    POST /api/v1/inventory

    Accept a JSON payload from Ansible and upsert the server record.

    Success response (200):
        {"status": "success", "action": "created"|"updated",
         "hostname": "<hostname>", "message": "Inventory updated"}

    Error responses:
        401  {"status": "error", "message": "Unauthorized"}
        400  {"status": "error", "message": "<reason>"}
        500  {"status": "error", "message": "Internal server error"}
    """
    # ── Authentication ─────────────────────────────────────────────────
    if not _authenticate():
        logger.warning(
            "Unauthorized API request from %s",
            request.remote_addr,
        )
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    # ── Content-type guard ─────────────────────────────────────────────
    if not request.is_json:
        return (
            jsonify({"status": "error", "message": "Content-Type must be application/json"}),
            400,
        )

    # ── Parse body ─────────────────────────────────────────────────────
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        return jsonify({"status": "error", "message": "Malformed JSON body"}), 400

    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "JSON body must be an object"}), 400

    # ── Validate ───────────────────────────────────────────────────────
    validation_error = validate_inventory_payload(data)
    if validation_error:
        return jsonify({"status": "error", "message": validation_error}), 400

    # ── Upsert ─────────────────────────────────────────────────────────
    result = upsert_server(data)
    if not result.success:
        return (
            jsonify({"status": "error", "message": result.error or "Internal server error"}),
            500,
        )

    return (
        jsonify(
            {
                "status": "success",
                "action": result.action,
                "hostname": result.hostname,
                "message": "Inventory updated",
            }
        ),
        200,
    )


# ── Health check (unauthenticated) ────────────────────────────────────── #

@api_bp.route(f"{API_PREFIX}/health", methods=["GET"])
@csrf.exempt
def health():
    """GET /api/v1/health — liveness probe, no auth required."""
    return jsonify({"status": "ok", "version": "1.0"}), 200
