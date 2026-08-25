"""Shared HTTP Basic Auth, used by both V1 (app.py) and V2 (web/v2.py) routes.

Moved out of app.py so V2 routes can reuse it without a circular import
between app.py and web/v2.py. Behavior is unchanged from V1.
"""
import functools
import os

from flask import request, session


def _check_auth(username: str, password: str) -> bool:
    admin_ok = (username == os.environ.get("ADMIN_USERNAME")
                and password == os.environ.get("ADMIN_PASSWORD"))
    demo_ok = (username == os.environ.get("DEMO_USERNAME")
               and password == os.environ.get("DEMO_PASSWORD"))
    return admin_ok or demo_ok


def _is_admin(username: str) -> bool:
    return username == os.environ.get("ADMIN_USERNAME")


def _is_admin_request() -> bool:
    """True if the current request is authenticated as admin (used to exempt rate limits)."""
    auth = request.authorization
    if auth and _check_auth(auth.username, auth.password) and _is_admin(auth.username):
        return True
    return _is_admin(session.get("username", ""))


def _request_auth():
    return (
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Back-End Assembly Line Simulator"'},
    )


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if auth and _check_auth(auth.username, auth.password):
            return f(*args, **kwargs, username=auth.username)
        username = session.get("username")
        if username:
            return f(*args, **kwargs, username=username)
        return _request_auth()
    return decorated
