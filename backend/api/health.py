"""Liveness probe without starting collectors or reading personal logs."""

from flask import Blueprint, jsonify
import os


blueprint = Blueprint("health", __name__)


@blueprint.get("/health")
def health():
    response = jsonify(app="token-observatory", version=2)
    response.headers["X-Token-Observatory-Pid"] = str(os.getpid())
    return response
