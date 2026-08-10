"""FastAPI web app: serves the chat UI and a separate login page.

Auth is handled entirely server-side. The ``/login`` page is a plain HTML form
that posts email/password to ``POST /auth/login``; the backend authenticates
against Supabase with the Python client, keeps the returned session (tokens +
user) in an in-memory store, and hands the browser only an opaque session id in
an HttpOnly cookie. From then on ``GET /`` and ``POST /ask`` are gated by looking
that id up — there is no auth logic in the frontend. Protected endpoints are
also rate limited.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import Client, create_client
from supabase_auth.errors import AuthApiError

from . import commands, context_store
from .agent import AgentEvent, build_agent
from .config import settings
from .logging_config import setup_logging
from .plan import TrainingPlan

# Configure logging at import time so it is active under uvicorn's reloader,
# where the worker imports this module directly without going through main().
setup_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Shown to the user for every login failure, whatever the underlying cause, so
# the response can't be used to tell registered emails from unregistered ones.
_GENERIC_LOGIN_ERROR = "Invalid email or password."

# Hosts for which an insecure (non-TLS) session cookie is acceptable.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


# --- Auth state ------------------------------------------------------------


@dataclass(frozen=True)
class AuthUser:
    """The authenticated principal handed to protected routes."""

    id: str
    email: str | None


@dataclass
class _Session:
    """A server-side session: the Supabase tokens kept behind an opaque id."""

    user: AuthUser
    access_token: str
    refresh_token: str
    expires_at: int | None  # unix seconds; None means no expiry


# Opaque-session-id -> session. In-memory and process-local: it is cleared on
# restart and not shared across workers, which is fine for this single-worker
# demo. Swap for Redis/a DB to survive restarts or scale out.
_sessions: dict[str, _Session] = {}

_supabase: Client | None = None


def _get_supabase() -> Client:
    """Lazily build the Supabase client from settings.

    Built on first use rather than at import so the app still starts when creds
    are absent; an unconfigured deployment then fails loudly only when someone
    actually tries to log in.
    """
    global _supabase
    if _supabase is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication is not configured.",
            )
        _supabase = create_client(settings.supabase_url, settings.supabase_key)
    return _supabase


def _lookup_session(session_id: str | None) -> _Session | None:
    """Resolve an opaque cookie value to a live session, dropping expired ones."""
    if not session_id:
        return None
    sess = _sessions.get(session_id)
    if sess is None:
        return None
    if sess.expires_at is not None and time.time() >= sess.expires_at:
        _sessions.pop(session_id, None)
        return None
    return sess


def optional_user(request: Request) -> AuthUser | None:
    """Return the signed-in user for this request, or None if not authenticated."""
    sess = _lookup_session(request.cookies.get(settings.auth_cookie_name))
    return sess.user if sess else None


def require_user(user: AuthUser | None = Depends(optional_user)) -> AuthUser:
    """Like ``optional_user`` but rejects requests without a valid session."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


def _rate_limit_key(request: Request) -> str:
    """Bucket rate limits per authenticated user, falling back to client IP.

    The key func runs before route dependencies, so we resolve the opaque
    session cookie to a user id via a cheap store lookup — this only decides
    *which bucket* a request counts against, never whether it is authorized
    (the auth dependency does that).
    """
    sess = _lookup_session(request.cookies.get(settings.auth_cookie_name))
    if sess:
        key = "rate limit:" + str(sess.user.id)
        return key # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string
    return get_remote_address(request)


# --- App setup -------------------------------------------------------------


def _warn_if_cookie_insecure() -> None:
    """Loudly warn when the session cookie would be sent without TLS off-host.

    ``cookie_secure`` defaults to False so the app works over http://127.0.0.1
    in local dev. If the app is bound to a non-loopback interface with that
    still off, the opaque session id can travel in cleartext and be captured —
    so surface it at startup rather than relying on the operator to remember.
    """
    if not settings.cookie_secure and settings.host not in _LOOPBACK_HOSTS:
        logger.warning(
            "cookie_secure is False but host=%s is not loopback: session "
            "cookies will be sent over plain HTTP. Set COOKIE_SECURE=true when "
            "serving over HTTPS.",
            settings.host,
        )


limiter = Limiter(key_func=_rate_limit_key)

_warn_if_cookie_insecure()

app = FastAPI(
    title=settings.app_title,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
agent = build_agent()


@app.middleware("http")
async def _no_store_static_assets(request: Request, call_next):
    """StaticFiles sets no Cache-Control header at all, so a browser's own
    heuristic caching can keep serving an old app.js/styles.css after a
    redeploy without ever re-checking the server -- confirmed live (a
    feature shipped in app.js silently didn't show up for a returning
    browser). GET /'s own no-store doesn't help, since it's the referenced
    static files that go stale, not the HTML. Negligible cost at this app's
    real traffic (single athlete, tiny files)."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class AskRequest(BaseModel):
    # max_length bounds worst-case per-request cost -- combined with
    # RATE_LIMIT_ASK, an unbounded field would let 20 huge questions/minute
    # through unchecked. 4000 chars is generous for a chat message (roughly
    # 1000 tokens) with headroom for a pasted workout log or similar.
    question: str = Field(min_length=1, max_length=4000)


def _render_login(error: str | None = None) -> HTMLResponse:
    """Serve the login page, injecting an error message where ``<!--ERROR-->``
    sits in the static HTML. Avoids a template engine and any client-side JS."""
    html = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    banner = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(html.replace("<!--ERROR-->", banner))


# --- Pages -----------------------------------------------------------------


@app.get("/", response_model=None)
async def index(
    user: AuthUser | None = Depends(optional_user),
) -> FileResponse | RedirectResponse:
    """Serve the chat UI — only to an authenticated session; else go to login."""
    if user is None:
        return RedirectResponse("/login", status_code=303)
    # Mark the authenticated page non-cacheable. Without this the browser caches
    # index.html and re-serves it for GET / (including back/forward navigation)
    # after logout, never re-hitting the server to get the redirect to /login.
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/plan", response_model=None)
async def plan_page(
    user: AuthUser | None = Depends(optional_user),
) -> FileResponse | RedirectResponse:
    """Serve the training-plan page — only to an authenticated session; else
    go to login. Same shape as index()."""
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(
        STATIC_DIR / "plan.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/login", response_model=None)
async def login_page(
    error: str | None = None,
    user: AuthUser | None = Depends(optional_user),
) -> HTMLResponse | RedirectResponse:
    """Serve the login page; bounce already-authenticated users to the chat."""
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return _render_login(error)


@app.get("/config")
async def config(
    user: AuthUser = Depends(require_user)
) -> dict[str, Any]:
    """Config the chat page reads: the title, and the slash-command list (the
    same commands.COMMANDS dict /help reads from) so the UI can surface them
    while the athlete types, instead of only via /help once they know to ask."""
    return {"title": settings.app_title, "commands": dict(commands.COMMANDS)}


_NO_PROFILE_GREETING = (
    "Hi! I don't have your athlete profile yet — tell me your sport, your "
    "current goal, and roughly when you're aiming for it, and I'll take it "
    "from there."
)


@app.get("/greeting")
async def greeting(user: AuthUser = Depends(require_user)) -> dict[str, str]:
    """A deterministic, no-LLM-call welcome shown before the athlete types
    anything: what context is already stored, or a prompt to start giving it.
    Never sent to the model and never persisted — purely a UI-layer greeting.
    """
    profile = context_store.get_profile(user.id)
    if not profile:
        return {"text": _NO_PROFILE_GREETING}
    return {"text": "Welcome back! Here's the context I'm working with:\n\n" + commands.format_profile(profile)}


# --- Training plan -----------------------------------------------------------


@app.get("/plan/data")
async def plan_data(user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    """The athlete's stored plan (or None) plus live-computed actuals, for
    plan.js to render. Actuals are never persisted — always computed fresh
    from real exercise data, matching the DoD's "only the visualisation lives
    on the HTML page"."""
    plan = context_store.get_plan(user.id)
    if plan is None:
        return {"plan": None, "actuals": []}

    # Lazily imported: exercise_insights pulls in pandas/numpy/boto3, which
    # noticeably slows app startup if paid on every server boot instead of
    # only when this route is actually hit (same pattern tools.py already
    # uses for get_exercise_metrics).
    from exercise_insights.core import get_weekly_actuals

    actuals = get_weekly_actuals(settings.polar_user_id, plan["start_date"], len(plan["weeks"]))
    return {"plan": plan, "actuals": actuals}


@app.post("/plan/edit")
async def plan_edit(
    req: TrainingPlan,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    """Manual full-replace edit of the athlete's training plan (the same
    validated shape save_training_plan writes — see plan.py)."""
    return context_store.save_plan(
        user.id,
        start_date=req.start_date,
        weeks=[w.model_dump() for w in req.weeks],
        themes=[t.model_dump() for t in req.themes],
    )


# --- Session management ----------------------------------------------------


@app.post("/auth/login", response_model=None)
@limiter.limit(settings.rate_limit_login)
def auth_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    """Authenticate email/password with Supabase, store the returned session
    server-side, and hand the browser only an opaque session id.

    Defined as a sync ``def`` so FastAPI runs the blocking Supabase call in a
    threadpool rather than on the event loop.
    """
    # Email is PII: keep it out of the INFO/production logs (which persist to a
    # rotating file). It is available at DEBUG for diagnosing a specific login.
    logger.debug("Login attempt for email=%s", email)
    try:
        result = _get_supabase().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError as exc:
        # Log the real Supabase reason server-side for diagnosis, but show the
        # user a single generic message regardless of cause. Distinct messages
        # ("Invalid login credentials" vs "Email not confirmed") would let an
        # attacker enumerate which emails are registered.
        logger.warning("Login failed: %s", exc.message)
        return RedirectResponse(
            f"/login?error={quote(_GENERIC_LOGIN_ERROR)}", status_code=303
        )

    session = result.session
    if session is None:  # e.g. email-confirmation required: no session issued
        # Same generic message as a credential failure, for the same
        # enumeration-resistance reason; the real cause stays in the log.
        logger.warning("Login returned no session (email confirmation pending?)")
        return RedirectResponse(
            f"/login?error={quote(_GENERIC_LOGIN_ERROR)}",
            status_code=303,
        )

    # Mint an opaque id and keep the Supabase tokens server-side behind it; the
    # browser only ever sees this id, never a JWT.
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = _Session(
        user=AuthUser(id=session.user.id, email=session.user.email),
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_at=session.expires_at,
    )

    # Expire the cookie alongside the underlying token; else a session cookie.
    max_age = (
        max(0, int(session.expires_at - time.time()))
        if session.expires_at is not None
        else None
    )

    logger.info("Login succeeded for user_id=%s", session.user.id)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        key=settings.auth_cookie_name,
        value=session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    return resp


@app.post("/auth/logout", response_model=None)
async def logout(request: Request) -> RedirectResponse:
    """Drop the server-side session, clear the cookie, return to login."""
    logger.info("Logout requested")
    session_id = request.cookies.get(settings.auth_cookie_name)
    if session_id:
        _sessions.pop(session_id, None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(settings.auth_cookie_name, path="/")
    return resp


# --- Agent -----------------------------------------------------------------


def _sse(event: AgentEvent) -> str:
    """Format an AgentEvent as a Server-Sent Event frame."""
    return f"data: {json.dumps(event)}\n\n"


_ONBOARDING_INSTRUCTION = (
    "This athlete has no coaching profile saved yet. Before giving substantive coaching "
    "advice, gather sport, goal, goal date/timeframe, desired outcome, constraints "
    "(injuries, time, equipment), preferred training approach, and how they'd like you to "
    "communicate (tone, brevity, directness) through natural conversation -- one or two "
    "questions at a time, not an interrogation. Once you have enough, call "
    "save_athlete_profile, briefly confirm what you saved, and proceed."
)

_REFRESH_PENDING_INSTRUCTION = (
    "The athlete ran /refresh-data just before this message -- their training data was "
    "force-refreshed from source moments ago. Call get_my_training_data again for this "
    "turn even if older metrics already appear earlier in this conversation; do not reuse "
    "stale values."
)


@app.post("/ask")
@limiter.limit(settings.rate_limit_ask)
async def ask(
    request: Request,
    req: AskRequest,
    user: AuthUser = Depends(require_user)
) -> StreamingResponse:
    """Stream the agent's answer as SSE. Requires a valid session cookie."""
    # Log the question text only at DEBUG so production (INFO) logs never capture
    # user content; INFO records just who asked and how long the question was.
    logger.info("Ask from user_id=%s (%d chars)", user.id, len(req.question))
    logger.debug("Ask from user_id=%s: %r", user.id, req.question[:500])

    if commands.is_command(req.question):
        outcome = commands.handle_command(req.question, user.id)
        if outcome.direct_reply is not None:
            async def command_stream() -> AsyncIterator[str]:
                yield _sse({"type": "text", "text": outcome.direct_reply})
                yield _sse({"type": "done"})

            return StreamingResponse(command_stream(), media_type="text/event-stream")
        extra_system = outcome.extra_system
    else:
        profile = context_store.get_profile(user.id)
        if profile:
            extra_system = (
                f"The athlete's stored coaching profile: {json.dumps(profile)}. Use it to "
                "frame your coaching without re-asking for it. If they mention something "
                "has changed, call save_athlete_profile again with the updated fields."
            )
        else:
            extra_system = _ONBOARDING_INSTRUCTION

    if context_store.consume_refresh_pending(user.id):
        extra_system = f"{extra_system}\n\n{_REFRESH_PENDING_INSTRUCTION}"

    plan = context_store.get_plan(user.id)
    if plan:
        extra_system = (
            f"{extra_system}\n\nThe athlete's current training plan: {json.dumps(plan)}. "
            "Reference it if relevant, but don't try to create or edit it from this chat -- "
            "point the athlete to the training plan page for that."
        )

    history = context_store.get_history(user.id)["messages"]

    async def event_stream() -> AsyncIterator[str]:
        context_store.current_user_id.set(user.id)
        async for event in agent.stream(req.question, history=history, extra_system=extra_system):
            if event.get("type") == "done" and "new_messages" in event:
                context_store.append_messages(user.id, event["new_messages"])
                if "usage" in event:
                    context_store.record_usage(user.id, event["usage"])
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


_PLAN_NO_PLAN_INSTRUCTION = (
    "This athlete doesn't have a training plan yet. Help them create one: gather how many "
    "weeks and their goal/target, and any themed periods they want (e.g. base building, "
    "taper), call get_my_training_data to ground weekly volumes and elevation in their real "
    "recent fitness, then call save_training_plan with the whole plan."
)


@app.post("/plan/ask")
@limiter.limit(settings.rate_limit_ask)
async def plan_ask(
    request: Request,
    req: AskRequest,
    user: AuthUser = Depends(require_user),
) -> StreamingResponse:
    """Stream the plan-construction agent's answer as SSE. Mirrors /ask's
    structure, but a separate agent persona (base_system=get_plan_system_prompt()),
    a separate history (kind="plan_conversation"), and no slash-command routing --
    this chat is scoped to plan creation/editing, not the full coach-page surface."""
    logger.info("Plan ask from user_id=%s (%d chars)", user.id, len(req.question))
    logger.debug("Plan ask from user_id=%s: %r", user.id, req.question[:500])

    plan = context_store.get_plan(user.id)
    if plan:
        extra_system = (
            f"The athlete's current training plan: {json.dumps(plan)}. Revise it based on "
            "what they ask for, keeping everything else unchanged, and call save_training_plan "
            "with the complete updated plan -- it replaces the whole stored plan, not a patch."
        )
    else:
        extra_system = _PLAN_NO_PLAN_INSTRUCTION

    history = context_store.get_history(user.id, kind="plan_conversation")["messages"]

    async def event_stream() -> AsyncIterator[str]:
        context_store.current_user_id.set(user.id)
        async for event in agent.stream(
            req.question,
            history=history,
            extra_system=extra_system,
            base_system=context_store.get_plan_system_prompt(),
        ):
            if event.get("type") == "done" and "new_messages" in event:
                context_store.append_messages(user.id, event["new_messages"], kind="plan_conversation")
                if "usage" in event:
                    context_store.record_usage(user.id, event["usage"])
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
