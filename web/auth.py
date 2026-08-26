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


def require_auth(f=None, *, auto_demo=False):
    """auto_demo=True silently logs a session-less visitor in as the demo
    user (same env-stored, no-real-secret credentials as /demo and
    /demo/v2) instead of showing a login prompt -- for the few read-only
    pages meant to work as cold shareable links (e.g. a Compare Runs URL
    sent to a hiring manager who won't have visited /demo/v2 first)."""
    def decorator(view):
        @functools.wraps(view)
        def decorated(*args, **kwargs):
            auth = request.authorization
            if auth and _check_auth(auth.username, auth.password):
                return view(*args, **kwargs, username=auth.username)
            username = session.get("username")
            if username:
                return view(*args, **kwargs, username=username)
            if auto_demo:
                demo_username = os.environ.get("DEMO_USERNAME", "")
                session["username"] = demo_username
                return view(*args, **kwargs, username=demo_username)
            return _request_auth()
        return decorated
    if f is not None:
        return decorator(f)
    return decorator
