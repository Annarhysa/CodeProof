"""
GitHub OAuth login (Connect GitHub -> pick a repo -> pick an issue), on top
of the read-only single-issue-URL flow in backend/app/github.py.

Session storage: Starlette's SessionMiddleware (signed cookie, set on
backend.app.main.app). This is a hackathon-appropriate simplification — the
cookie is tamper-proof (signed) but not encrypted, so treat SESSION_SECRET_KEY
as sensitive and don't store anything more sensitive than a GitHub OAuth
token in the session. Good enough for local/single-user demo use; a
production deployment would want server-side session storage instead.
"""
from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/auth/github", tags=["github-auth"])

GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API = "https://api.github.com"


def _client_id() -> str:
    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
    if not client_id:
        raise HTTPException(500, "GITHUB_OAUTH_CLIENT_ID not configured in .env")
    return client_id


def _redirect_uri() -> str:
    # Must be "localhost", not "127.0.0.1" — the pre-redirect session cookie
    # (holding oauth_state) is scoped to whatever host the browser saw for
    # the initial /login request, and browsers treat these as different
    # hosts for cookie purposes even though they're the same machine.
    return os.environ.get("GITHUB_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/github/callback")


def _frontend_url() -> str:
    return os.environ.get("CODEPROOF_FRONTEND_URL", "http://localhost:5173")


def _require_token(request: Request) -> str:
    token = request.session.get("github_token")
    if not token:
        raise HTTPException(401, "GitHub not connected. Call /auth/github/login first.")
    return token


@router.get("/login")
def login(request: Request):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "scope": "repo",
        "state": state,
    }
    return RedirectResponse(f"{GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/callback")
def callback(request: Request, code: str, state: str):
    if not state or state != request.session.get("oauth_state"):
        raise HTTPException(400, "invalid OAuth state (possible CSRF or expired session)")
    request.session.pop("oauth_state", None)

    token_resp = requests.post(
        GITHUB_OAUTH_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": _client_id(),
            "client_secret": os.environ.get("GITHUB_OAUTH_CLIENT_SECRET"),
            "code": code,
            "redirect_uri": _redirect_uri(),
        },
        timeout=15,
    )
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, f"GitHub OAuth token exchange failed: {token_data}")

    user_resp = requests.get(
        f"{GITHUB_API}/user", headers={"Authorization": f"Bearer {access_token}"}, timeout=15,
    )
    if user_resp.status_code != 200:
        raise HTTPException(400, f"Could not fetch GitHub user profile: {user_resp.status_code}")

    request.session["github_token"] = access_token
    request.session["github_user"] = user_resp.json().get("login")
    return RedirectResponse(f"{_frontend_url()}/new")


@router.get("/me")
def me(request: Request) -> dict:
    user = request.session.get("github_user")
    if not user:
        raise HTTPException(401, "not connected")
    return {"login": user}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/repos")
def list_repos(request: Request) -> list[dict]:
    token = _require_token(request)
    resp = requests.get(
        f"{GITHUB_API}/user/repos",
        headers={"Authorization": f"Bearer {token}"},
        params={"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text[:300])
    return [
        {
            "full_name": r["full_name"],
            "owner": r["owner"]["login"],
            "name": r["name"],
            "private": r["private"],
            "html_url": r["html_url"],
            "open_issues_count": r.get("open_issues_count", 0),
        }
        for r in resp.json()
    ]


@router.get("/repos/{owner}/{repo}/issues")
def list_issues(owner: str, repo: str, request: Request) -> list[dict]:
    token = _require_token(request)
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues",
        headers={"Authorization": f"Bearer {token}"},
        params={"state": "open", "per_page": 50},
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text[:300])
    # GitHub's issues endpoint also returns pull requests; filter those out.
    return [
        {"number": i["number"], "title": i["title"], "state": i["state"], "html_url": i["html_url"]}
        for i in resp.json()
        if "pull_request" not in i
    ]
