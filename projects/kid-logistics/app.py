"""Kid Logistics — the family schedule, and what to do when it changes.

    pip install -r requirements.txt
    KIDLOG_DEV=1 python -m uvicorn app:app --reload --port 8000

Then open http://127.0.0.1:8000. In production this must be served over HTTPS:
both Add to Home Screen and Web Push require a secure context, and the session
cookie is marked Secure unless KIDLOG_DEV is set.

The shape of the thing:

    week  ->  event  ->  something changed  ->  who needs telling  ->  tick them off

Everything on the left exists to make the right-hand end possible. The screen
that matters is the last one, and the list it shows is computed in changes.py
by code you can read — not by a model, and not by whoever remembers the
carpool arrangement at 6:40am.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import auth
import changes
import db
import links
import localtime as lt

BASE = Path(__file__).parent
SESSION_COOKIE = "kidlog_session"

#: Secure cookies unless explicitly developing on localhost. The wrong default
#: here is the one that silently works in testing and leaks in production.
DEV = os.environ.get("KIDLOG_DEV") == "1"

app = FastAPI(title="Kid Logistics")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


# ------------------------------------------------------------------ plumbing


def get_db() -> sqlite3.Connection:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_db)]


def current_user(request: Request, conn: Conn) -> auth.User | None:
    return auth.session_user(conn, request.cookies.get(SESSION_COOKIE))


CurrentUser = Annotated["auth.User | None", Depends(current_user)]


def household_tz(conn: sqlite3.Connection, user: auth.User) -> str:
    row = db.get_household(conn, user.household_id)
    return row["timezone"] if row else "America/New_York"


def platform_of(user: auth.User | None) -> str:
    return (user.platform if user and user.platform else links.ANDROID)


def render(
    request: Request, template: str, user: auth.User | None, **context: Any,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name=template,
        context={"user": user, "platform": platform_of(user), **context},
    )


def signin_redirect() -> RedirectResponse:
    return RedirectResponse("/signin", status_code=303)


def see(target: str) -> RedirectResponse:
    return RedirectResponse(target, status_code=303)


# ------------------------------------------------------------------ setup


@app.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, conn: Conn):
    if db.only_household(conn) is not None:
        return signin_redirect()
    return render(request, "setup.html", None, zones=_COMMON_ZONES, error=None)


#: Enough to cover most of the US without shipping a picker of 600 entries.
#: Any IANA name can be typed in Settings afterwards.
_COMMON_ZONES = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Phoenix", "America/Anchorage",
    "Pacific/Honolulu", "Europe/London",
]


@app.post("/setup")
def setup(
    request: Request, conn: Conn,
    household: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    name: Annotated[str, Form()],
    passcode: Annotated[str, Form()],
):
    if db.only_household(conn) is not None:
        return signin_redirect()
    try:
        lt.zone(timezone)
    except Exception:
        return render(request, "setup.html", None, zones=_COMMON_ZONES,
                      error=f"{timezone!r} is not a timezone name")
    try:
        hid = db.create_household(conn, household.strip() or "Home", timezone)
        user = auth.create_user(conn, hid, name, passcode)
    except auth.AuthError as exc:
        return render(request, "setup.html", None, zones=_COMMON_ZONES,
                      error=str(exc))

    # The first account is also a person in the household, so the app can keep
    # you off your own list of people to text.
    person = db.add_person(conn, hid, name.strip().title(), db.ADULT)
    auth.link_person(conn, user.id, person)
    auth.set_platform(conn, user.id,
                      auth.detect_platform(request.headers.get("user-agent")))
    return _start_session(conn, user, "/settings")


# ------------------------------------------------------------------ sessions


def _start_session(conn, user: auth.User, target: str) -> RedirectResponse:
    token = auth.start_session(conn, user)
    response = see(target)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400,
        httponly=True, samesite="lax", secure=not DEV,
    )
    return response


@app.get("/signin", response_class=HTMLResponse)
def signin_form(request: Request, conn: Conn, user: CurrentUser):
    if db.only_household(conn) is None:
        return see("/setup")
    if user:
        return see("/")
    return render(request, "signin.html", None, error=None)


@app.post("/signin")
def signin(
    request: Request, conn: Conn,
    name: Annotated[str, Form()], passcode: Annotated[str, Form()],
):
    try:
        user = auth.verify(conn, name, passcode)
    except auth.AuthError as exc:
        return render(request, "signin.html", None, error=str(exc))
    if not user.platform:
        auth.set_platform(conn, user.id,
                          auth.detect_platform(request.headers.get("user-agent")))
    return _start_session(conn, user, "/")


@app.post("/signout")
def signout(request: Request, conn: Conn):
    auth.end_session(conn, request.cookies.get(SESSION_COOKIE))
    response = see("/signin")
    response.delete_cookie(SESSION_COOKIE)
    return response


# ------------------------------------------------------------------ the week


def _decorate(conn, events: list[db.Event], tz: str, today: date) -> list[dict]:
    """Attach to each event the things every list view wants to show."""
    out = []
    for event in events:
        people = db.casting(conn, event.id)
        out.append({
            "event": event,
            "when": lt.fmt_when(event.starts_at_utc, tz, today),
            "time": lt.fmt_time(event.starts_at_utc, tz),
            "day": lt.fmt_day(event.starts_at_utc, tz),
            "date": lt.to_local(event.starts_at_utc, tz).date(),
            "kids": [c.who for c in people
                     if c.is_household and c.role == db.ROLE_ATTENDING],
            "drivers": [c.name for c in people if c.role in db.DRIVING_ROLES],
            "casting": people,
        })
    return out


@app.get("/", response_class=HTMLResponse)
def week(request: Request, conn: Conn, user: CurrentUser, start: str | None = None):
    if not user:
        return signin_redirect()
    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    anchor = date.fromisoformat(start) if start else today
    begins, ends = lt.week_bounds(tz, anchor)

    events = db.events_between(conn, user.household_id, begins, ends)
    decorated = _decorate(conn, events, tz, today)

    monday = lt.to_local(begins, tz).date()
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        days.append({
            "date": day,
            "label": f"{lt.DAY_NAMES[day.weekday()]} {day.day} {day.strftime('%B')}",
            "is_today": day == today,
            "events": [d for d in decorated if d["date"] == day],
        })

    return render(
        request, "week.html", user,
        days=days, kids=db.list_people(conn, user.household_id, db.KID),
        monday=monday, prev=monday - timedelta(days=7),
        next=monday + timedelta(days=7), today=today,
        is_this_week=monday == today - timedelta(days=today.weekday()),
        count=len(decorated),
        unresolved=_unresolved(conn, user.household_id),
    )


def _unresolved(conn, household_id: str) -> int:
    """Changes with someone still unticked — the badge on the week view."""
    rows = conn.execute(
        "SELECT c.recipients_json, c.told_json FROM changes c"
        " JOIN events e ON e.id = c.event_id WHERE e.household_id = ?"
        " ORDER BY c.made_at DESC LIMIT 50",
        (household_id,),
    ).fetchall()
    import json
    total = 0
    for row in rows:
        recipients = json.loads(row["recipients_json"] or "[]")
        told = json.loads(row["told_json"] or "{}")
        if any(r["key"] not in told and r.get("phone") for r in recipients):
            total += 1
    return total


@app.get("/day/{when}", response_class=HTMLResponse)
def day(request: Request, conn: Conn, user: CurrentUser, when: str):
    if not user:
        return signin_redirect()
    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    target = date.fromisoformat(when)
    begins, ends = lt.day_bounds(tz, target)
    events = db.events_between(conn, user.household_id, begins, ends)
    return render(
        request, "day.html", user,
        day=target,
        label=f"{lt.DAY_NAMES[target.weekday()]} {target.day} {target.strftime('%B')}",
        rows=_decorate(conn, events, tz, today),
        prev=target - timedelta(days=1), next=target + timedelta(days=1),
    )


@app.get("/kid/{person_id}", response_class=HTMLResponse)
def kid(request: Request, conn: Conn, user: CurrentUser, person_id: str,
        start: str | None = None):
    if not user:
        return signin_redirect()
    person = db.get_person(conn, person_id)
    if person is None or person.household_id != user.household_id:
        return see("/")
    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    anchor = date.fromisoformat(start) if start else today
    begins, ends = lt.week_bounds(tz, anchor)
    events = db.events_between(conn, user.household_id, begins, ends,
                               person_id=person_id)
    monday = lt.to_local(begins, tz).date()
    return render(
        request, "kid.html", user, person=person,
        rows=_decorate(conn, events, tz, today),
        checkin=links.checkin_url(person.checkin_url),
        monday=monday, prev=monday - timedelta(days=7),
        next=monday + timedelta(days=7),
        contacts=db.list_contacts(conn, user.household_id),
    )


# ------------------------------------------------------------------ an event


@app.get("/event/{event_id}", response_class=HTMLResponse)
def event_page(request: Request, conn: Conn, user: CurrentUser, event_id: str):
    if not user:
        return signin_redirect()
    event = db.get_event(conn, event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")
    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    people = db.casting(conn, event.id)
    history = db.event_changes(conn, event.id)

    return render(
        request, "event.html", user, event=event,
        when=lt.fmt_when(event.starts_at_utc, tz, today),
        ends=lt.fmt_time(event.ends_at_utc, tz) if event.ends_at_utc else None,
        casting=people,
        role_labels=ROLE_LABELS,
        people=db.list_people(conn, user.household_id),
        contacts=db.list_contacts(conn, user.household_id),
        maps=links.maps_urls(event.location_address),
        history=[{
            "change": c,
            "label": changes.REASON_LABELS.get(c.reason, c.reason),
            "when": lt.fmt_when(c.made_at, tz, today),
            "outstanding": [r for r in c.recipients if r["key"] not in c.told],
        } for c in history],
        tel=lambda phone: links.tel_url(phone),
        checkin=links.checkin_url,
    )


ROLE_LABELS = {
    db.ROLE_ATTENDING: "going",
    db.ROLE_DRIVING_THERE: "driving there",
    db.ROLE_DRIVING_HOME: "driving home",
    db.ROLE_CARPOOL: "carpool",
    db.ROLE_NOTIFY: "to notify",
}


# ------------------------------------------------------------------ the change


@app.get("/event/{event_id}/change", response_class=HTMLResponse)
def change_form(request: Request, conn: Conn, user: CurrentUser, event_id: str,
                reason: str | None = None, sick: str | None = None):
    if not user:
        return signin_redirect()
    event = db.get_event(conn, event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")
    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    people = db.casting(conn, event.id)

    return render(
        request, "change.html", user, event=event,
        when=lt.fmt_when(event.starts_at_utc, tz, today),
        reasons=[(r, changes.REASON_LABELS[r]) for r in changes.REASONS],
        reason=reason,
        attending=[c for c in people
                   if c.is_household and c.role == db.ROLE_ATTENDING],
        sick=sick,
        ask_driving=bool(sick) and changes.needs_driving_question(people, sick),
        error=None,
    )


@app.post("/event/{event_id}/change")
def change_submit(
    request: Request, conn: Conn, user: CurrentUser, event_id: str,
    reason: Annotated[str, Form()],
    sick_person_id: Annotated[str, Form()] = "",
    still_driving: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    late_minutes: Annotated[str, Form()] = "",
    new_location: Annotated[str, Form()] = "",
):
    if not user:
        return signin_redirect()
    event = db.get_event(conn, event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")

    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    people = db.casting(conn, event.id)
    driving = {"yes": True, "no": False}.get(still_driving)

    ctx = changes.Context(
        when=lt.fmt_when(event.starts_at_utc, tz, today),
        sick_name=(db.get_person(conn, sick_person_id).name
                   if sick_person_id else None),
        still_driving=driving,
        late_minutes=int(late_minutes) if late_minutes.strip().isdigit() else None,
        new_location=new_location.strip() or None,
        note=note.strip() or None,
        signature=(db.get_person(conn, user.person_id).name
                   if user.person_id else user.name),
    )

    try:
        recipients = changes.affected(
            event, people, reason,
            sick_person_id=sick_person_id or None,
            still_driving=driving,
            household_adults=db.list_people(conn, user.household_id, db.ADULT),
            exclude=[user.key] if user.key else [],
        )
    except changes.ChangeError as exc:
        # The commonest case is the app declining to guess whether you are
        # still driving. Re-ask rather than inventing an answer.
        return render(
            request, "change.html", user, event=event,
            when=lt.fmt_when(event.starts_at_utc, tz, today),
            reasons=[(r, changes.REASON_LABELS[r]) for r in changes.REASONS],
            reason=reason,
            attending=[c for c in people
                       if c.is_household and c.role == db.ROLE_ATTENDING],
            sick=sick_person_id or None,
            ask_driving=bool(sick_person_id) and changes.needs_driving_question(
                people, sick_person_id),
            error=str(exc),
        )

    # The message you are about to send is stored with the change, so the
    # history shows what was actually said rather than what a later version of
    # a template would say.
    stored = []
    for recipient in recipients:
        row = recipient.as_dict()
        row["draft"] = changes.draft(event, reason, recipient, ctx)
        stored.append(row)

    change_id = db.record_change(
        conn, event.id, reason, stored,
        note=ctx.note, made_by=user.name,
    )
    _apply(conn, event, reason, ctx)
    return see(f"/change/{change_id}")


def _apply(conn, event: db.Event, reason: str, ctx: changes.Context) -> None:
    """Update the event itself, so the schedule is a living document.

    Telling people is half the job; the other half is that whoever opens the
    app next sees the new truth rather than the old plan.
    """
    if reason == changes.EVENT_CANCELLED:
        db.update_event(conn, event.id, status=db.STATUS_CANCELLED)
    elif reason == changes.LOCATION_CHANGED and ctx.new_location:
        db.update_event(conn, event.id, status=db.STATUS_CHANGED,
                        location_name=ctx.new_location,
                        location_address=ctx.new_location)
    elif reason != changes.CUSTOM:
        db.update_event(conn, event.id, status=db.STATUS_CHANGED)


@app.get("/change/{change_id}", response_class=HTMLResponse)
def tell(request: Request, conn: Conn, user: CurrentUser, change_id: str):
    if not user:
        return signin_redirect()
    change = db.get_change(conn, change_id)
    if change is None:
        return see("/")
    event = db.get_event(conn, change.event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")

    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    platform = platform_of(user)

    rows = []
    for r in change.recipients:
        rows.append({
            **r,
            "told": r["key"] in change.told,
            "sms": links.sms_url(r.get("phone"), r.get("draft", ""), platform),
            "tel": links.tel_url(r.get("phone")),
        })
    outstanding = [r for r in rows if not r["told"] and r["phone"]]

    return render(
        request, "tell.html", user, change=change, event=event,
        when=lt.fmt_when(event.starts_at_utc, tz, today),
        label=changes.REASON_LABELS.get(change.reason, change.reason),
        rows=rows, outstanding=len(outstanding), total=len(rows),
        must_left=len([r for r in outstanding if r["urgency"] == changes.MUST]),
    )


@app.post("/change/{change_id}/told")
def told(request: Request, conn: Conn, user: CurrentUser, change_id: str,
         key: Annotated[str, Form()]):
    if not user:
        return signin_redirect()
    change = db.get_change(conn, change_id)
    if change is None:
        return see("/")
    event = db.get_event(conn, change.event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")
    db.mark_told(conn, change_id, key)
    return see(f"/change/{change_id}")


# ------------------------------------------------------------------ editing


@app.get("/event/new", response_class=HTMLResponse)
def new_event_form(request: Request, conn: Conn, user: CurrentUser,
                   when: str | None = None):
    if not user:
        return signin_redirect()
    tz = household_tz(conn, user)
    today = datetime.now(lt.zone(tz)).date()
    return render(
        request, "event_form.html", user,
        people=db.list_people(conn, user.household_id),
        contacts=db.list_contacts(conn, user.household_id),
        role_labels=ROLE_LABELS,
        default_date=(when or today.isoformat()),
        error=None,
    )


@app.post("/event/new")
def new_event(
    request: Request, conn: Conn, user: CurrentUser,
    title: Annotated[str, Form()],
    on: Annotated[str, Form()],
    at: Annotated[str, Form()],
    minutes: Annotated[str, Form()] = "90",
    location_name: Annotated[str, Form()] = "",
    location_address: Annotated[str, Form()] = "",
    bring: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    repeat_weeks: Annotated[str, Form()] = "1",
    attending: Annotated[list[str], Form()] = [],
    driving_there: Annotated[list[str], Form()] = [],
    carpool: Annotated[list[str], Form()] = [],
    notify: Annotated[list[str], Form()] = [],
):
    if not user:
        return signin_redirect()
    tz = household_tz(conn, user)

    def rerender(message: str):
        today = datetime.now(lt.zone(tz)).date()
        return render(request, "event_form.html", user,
                      people=db.list_people(conn, user.household_id),
                      contacts=db.list_contacts(conn, user.household_id),
                      role_labels=ROLE_LABELS,
                      default_date=on or today.isoformat(), error=message)

    if not title.strip():
        return rerender("the event needs a name")
    try:
        local_start = datetime.combine(
            date.fromisoformat(on), datetime.strptime(at, "%H:%M").time())
    except ValueError:
        return rerender("that date and time did not parse")

    weeks = int(repeat_weeks) if repeat_weeks.strip().isdigit() else 1
    weeks = max(1, min(weeks, 52))
    duration = timedelta(minutes=int(minutes)) if minutes.strip().isdigit() else None

    _, ids = db.add_series(
        conn, user.household_id, title.strip(), local_start, weeks, tz,
        duration=duration,
        location_name=location_name.strip() or None,
        location_address=location_address.strip() or None,
        bring=bring.strip() or None, notes=notes.strip() or None,
        created_by=user.name,
    )

    # The same cast on every occurrence of the series.
    for event_id in ids:
        for token in attending:
            _cast_token(conn, event_id, db.ROLE_ATTENDING, token)
        for token in driving_there:
            _cast_token(conn, event_id, db.ROLE_DRIVING_THERE, token)
        for token in carpool:
            _cast_token(conn, event_id, db.ROLE_CARPOOL, token)
        for token in notify:
            _cast_token(conn, event_id, db.ROLE_NOTIFY, token)

    return see(f"/event/{ids[0]}")


def _cast_token(conn, event_id: str, role: str, token: str) -> None:
    """`person:<id>` / `contact:<id>` from a form checkbox onto the event."""
    kind, _, ident = token.partition(":")
    if kind == "person":
        db.cast(conn, event_id, role, person_id=ident)
    elif kind == "contact":
        db.cast(conn, event_id, role, contact_id=ident)


@app.post("/event/{event_id}/cast")
def cast_one(request: Request, conn: Conn, user: CurrentUser, event_id: str,
             role: Annotated[str, Form()], who: Annotated[str, Form()]):
    if not user:
        return signin_redirect()
    event = db.get_event(conn, event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")
    _cast_token(conn, event_id, role, who)
    return see(f"/event/{event_id}")


@app.post("/event/{event_id}/uncast")
def uncast_one(request: Request, conn: Conn, user: CurrentUser, event_id: str,
               casting_id: Annotated[str, Form()]):
    if not user:
        return signin_redirect()
    event = db.get_event(conn, event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")
    db.uncast(conn, casting_id)
    return see(f"/event/{event_id}")


@app.post("/event/{event_id}/reinstate")
def reinstate(request: Request, conn: Conn, user: CurrentUser, event_id: str):
    if not user:
        return signin_redirect()
    event = db.get_event(conn, event_id)
    if event is None or event.household_id != user.household_id:
        return see("/")
    db.update_event(conn, event_id, status=db.STATUS_ON)
    return see(f"/event/{event_id}")


# ------------------------------------------------------------------ settings


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, conn: Conn, user: CurrentUser):
    if not user:
        return signin_redirect()
    row = db.get_household(conn, user.household_id)
    return render(
        request, "settings.html", user,
        household=row,
        people=db.list_people(conn, user.household_id),
        contacts=db.list_contacts(conn, user.household_id),
        users=auth.list_users(conn),
        palette=db.PALETTE,
        zones=_COMMON_ZONES,
    )


@app.post("/settings/person")
def add_person(
    request: Request, conn: Conn, user: CurrentUser,
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()] = db.KID,
    phone: Annotated[str, Form()] = "",
    color: Annotated[str, Form()] = "",
    checkin_url: Annotated[str, Form()] = "",
):
    if not user:
        return signin_redirect()
    if name.strip():
        db.add_person(conn, user.household_id, name.strip(), kind,
                      color=color or None, phone=phone.strip() or None,
                      checkin_url=checkin_url.strip() or None)
    return see("/settings")


@app.post("/settings/person/{person_id}")
def edit_person(
    request: Request, conn: Conn, user: CurrentUser, person_id: str,
    phone: Annotated[str, Form()] = "",
    color: Annotated[str, Form()] = "",
    checkin_url: Annotated[str, Form()] = "",
):
    if not user:
        return signin_redirect()
    person = db.get_person(conn, person_id)
    if person and person.household_id == user.household_id:
        db.update_person(conn, person_id, phone=phone.strip() or None,
                         color=color or person.color,
                         checkin_url=checkin_url.strip() or None)
    return see("/settings")


@app.post("/settings/contact")
def add_contact(
    request: Request, conn: Conn, user: CurrentUser,
    name: Annotated[str, Form()],
    phone: Annotated[str, Form()] = "",
    relation: Annotated[str, Form()] = "",
    org: Annotated[str, Form()] = "",
):
    if not user:
        return signin_redirect()
    if name.strip():
        db.add_contact(conn, user.household_id, name.strip(),
                       phone=phone.strip() or None,
                       relation=relation.strip() or None,
                       org=org.strip() or None)
    return see("/settings")


@app.post("/settings/me")
def settings_me(
    request: Request, conn: Conn, user: CurrentUser,
    platform: Annotated[str, Form()] = "",
    person_id: Annotated[str, Form()] = "",
    timezone: Annotated[str, Form()] = "",
):
    if not user:
        return signin_redirect()
    if platform in auth.PLATFORMS:
        auth.set_platform(conn, user.id, platform)
    if person_id:
        auth.link_person(conn, user.id, person_id)
    if timezone:
        try:
            lt.zone(timezone)
            conn.execute("UPDATE households SET timezone = ? WHERE id = ?",
                         (timezone, user.household_id))
            conn.commit()
        except Exception:
            pass
    return see("/settings")


@app.post("/settings/user")
def add_user(
    request: Request, conn: Conn, user: CurrentUser,
    name: Annotated[str, Form()], passcode: Annotated[str, Form()],
    person_id: Annotated[str, Form()] = "",
):
    """The second parent. Same household, same schedule, own passcode."""
    if not user:
        return signin_redirect()
    try:
        made = auth.create_user(conn, user.household_id, name, passcode)
        if person_id:
            auth.link_person(conn, made.id, person_id)
    except auth.AuthError:
        pass
    return see("/settings")


@app.get("/healthz")
def healthz(conn: Conn):
    return {"ok": True, "household": db.only_household(conn) is not None}
