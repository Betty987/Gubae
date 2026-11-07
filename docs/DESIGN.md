# Gubae: how it works and why it's built this way

This document explains Gubae's architecture and the reasoning behind its main design decisions. Each section links to the code it describes.

---

## 1. The big picture

```
┌──────────────────────┐   HTTP + JSON    ┌──────────────────────────┐   SQL   ┌───────────┐
│  React app (browser) │ ───────────────► │  Django + DRF (Python)   │ ──────► │ Database  │
│  localhost:5173      │ ◄─────────────── │  127.0.0.1:8000          │ ◄────── │ SQLite /  │
│  pages, forms, state │  Authorization:  │  auth, rules, queries    │         │ Postgres  │
└──────────────────────┘  Bearer <JWT>    └──────────────────────────┘         └───────────┘
                                                     ▲
                                  cron ─► python manage.py send_reminders ─► email
```

**It's a "decoupled" architecture.** The backend only speaks JSON and knows nothing about how pages look. The frontend is a separate app. That's why we need JWT: the frontend has to prove who it is on every request.

### Life of one request: "Dawit clicks *Going*"

1. **React** ([EventPage.tsx](../frontend/src/pages/EventPage.tsx)) calls `api.rsvp(12, "going")`.
2. **[api.ts](../frontend/src/api.ts)** sends `POST /api/events/12/rsvp/` with the header `Authorization: Bearer eyJ...`.
3. **The Vite proxy** forwards it from :5173 to Django on :8000.
4. **[config/urls.py](../gubae/config/urls.py) → [events/urls.py](../gubae/events/urls.py)** matches `events/<int:pk>/rsvp/`, which goes to the `EventRSVP` view with `pk=12`.
5. **SimpleJWT** checks the token signature and expiry and sets `request.user = Dawit`. A bad token returns **401**.
6. **`EventRSVP.post`** ([views.py](../gubae/events/views.py)) validates the input, locks the event row, checks membership, the start time and capacity, then saves.
7. **The serializer** turns the saved RSVP into JSON, and the response is **201 Created** (first RSVP) or **200 OK** (changed RSVP).
8. **React** reloads the event, so the counts come fresh from the server.


---

## 2. Folder map

```
p1/
├── gubae/                      ← BACKEND (Django project)
│   ├── manage.py               command-line entry point (runserver, migrate, test…)
│   ├── requirements.txt        exact Python package versions
│   ├── config/
│   │   ├── settings.py         configuration: apps, DB, JWT, permissions, throttling
│   │   └── urls.py             top-level router: /admin/, /api/, /api/auth/
│   ├── accounts/               "who are you?" (sign up, log in, me)
│   │   ├── serializers.py      RegisterSerializer (hashes password), UserSerializer
│   │   ├── views.py            Register, Login (rate-limited), Me
│   │   ├── urls.py
│   │   └── tests.py
│   └── events/                 "what's happening?" (the actual product)
│       ├── models.py           database tables
│       ├── migrations/         version history of the database schema
│       ├── serializers.py      JSON <-> Python, input validation
│       ├── permissions.py      who may do what
│       ├── views.py            endpoint logic
│       ├── urls.py             endpoint URLs
│       ├── admin.py            Django admin panel config
│       ├── ai.py               paste announcement -> draft event (Claude API)
│       ├── notifications.py    new-event emails + .ics calendar feeds
│       ├── management/commands/
│       │   ├── send_reminders.py   scheduled job
│       │   └── seed_demo.py        demo data
│       ├── tests.py            31 core tests
│       └── test_reach.py       16 tests for AI, emails, calendars (+6 in accounts = 53)
├── frontend/                   ← FRONTEND (React + TypeScript)
│   ├── vite.config.ts          dev server + proxy to Django
│   └── src/
│       ├── main.tsx            mounts <App/> into index.html
│       ├── App.tsx             routes + header + RequireAuth guard
│       ├── api.ts              the ONLY file that talks to the backend
│       ├── auth.tsx            login state shared app-wide (React Context)
│       ├── format.ts           date/slug helpers
│       ├── components/useLoad.ts   custom hook: loading/error/data/reload
│       ├── pages/              one file per screen
│       └── index.css           design tokens + all styles (light & dark)
└── docs/DESIGN.md              ← you are here
```

**Why split the backend into `accounts` and `events`?** *Separation of concerns.* Login has nothing to do with events. If we later add a `donations` app, it reuses `accounts` without touching `events`.

---

## 3. Data model ([models.py](../gubae/events/models.py))

```
User ──< Membership >── Community ──< Event ──< VolunteerSlot ──< VolunteerSignup >── User
 │        (role)                        │
 └──────────────< RSVP >────────────────┘
                 (status, reminded_at)
```

| Decision | Why | In one line |
|---|---|---|
| `role` lives on **Membership**, not User | A person can be an admin at one church and a member at another | "Role is a property of the relationship, so it lives on the join table." |
| `UniqueConstraint(user, event)` on RSVP | One RSVP per person per event, enforced by the **database** even if app code has a bug | "Defense in depth: validate in code, guarantee in the DB." |
| `CheckConstraint(ends_at > starts_at)` | Impossible data can't exist | Same |
| `Index(community, starts_at)` | The most common query is "upcoming events for this community" | "I indexed for my read pattern." |
| `capacity` nullable | `null` = unlimited, which is clearer than a magic number like 0 or 9999 | |
| `on_delete=CASCADE` on most FKs, `SET_NULL` on `created_by` | Deleting a community removes its events, but deleting a user shouldn't delete events they created | "I chose delete behavior per relationship." |
| Store UTC, display local (`USE_TZ=True`, `TIME_ZONE="America/New_York"`) | Daylight saving and users in different zones (family in Addis is 7–8h ahead) | "Store UTC, convert at the edges." |
| `RSVP.reminded_at` | Makes the reminder job idempotent (see §8) | |

**Migrations** (`events/migrations/0001…0003`) are version control for the schema. `makemigrations` writes the change, `migrate` applies it, and every teammate or server runs the same files.

---

## 4. Authentication: JWT ([accounts/](../gubae/accounts/), [settings.py](../gubae/config/settings.py))

**Passwords**
- `create_user()` stores `pbkdf2_sha256$1500000$salt$hash`: the password run through 1.5 million rounds of hashing with a random salt. It's never stored as plain text, and it can't be reversed.
- `password` is `write_only` in the serializer, so it's never sent back in a response.
- Django's validators reject `123`, `password` and anything too similar to the username.

**Tokens**
```
POST /api/auth/token/ {username, password}  →  {access (15 min), refresh (7 days)}
every request:  Authorization: Bearer <access>
access expired → POST /api/auth/token/refresh/ {refresh} → new access
```
- A JWT is `header.payload.signature`. The payload (`user_id`, `exp`) is **readable by anyone**, since it's base64 and not encrypted, but it **can't be forged** without the server's `SECRET_KEY`.
- **Stateless:** the server doesn't store sessions. It just checks the signature. That scales easily across many servers.
- **Short access and long refresh:** if an access token leaks, it's only useful for 15 minutes.
- **Rate limiting:** login and register allow 20 requests/min per IP (`throttle_scope = "auth"`), which slows down password guessing. Returns **429**.

**Tradeoffs to mention (they show maturity):**
| Choice | Downside | Upgrade path |
|---|---|---|
| Tokens in `localStorage` | Readable by JavaScript, so an XSS bug could steal them | httpOnly cookies, which JS can't read |
| Stateless JWT | You can't instantly revoke a token | SimpleJWT's refresh-token blacklist app |
| Logout = client forgets the token | The token stays valid until it expires | Blacklist the refresh token on logout |

---

## 5. Authorization: who may do what ([permissions.py](../gubae/events/permissions.py))

**Authentication** = *who are you?* (401 if unknown). **Authorization** = *are you allowed?* (403 if not).

| Action | Rule | Where it's enforced |
|---|---|---|
| Read communities and events | Anyone | `IsAuthenticatedOrReadOnly` (global default) |
| Create a community | Logged in, and the creator becomes admin | `CommunityListCreate.create` (in a transaction) |
| Create, edit or delete an event | Admin **of that event's community** | `is_admin_of` + `IsCommunityAdminOrReadOnly` |
| RSVP / volunteer | Member of that community | `is_member_of` in the views |
| See the guest list | Admin only (privacy) | `EventAttendees.get_queryset` |
| Leave a community | Not if you're the last admin | `CommunityMembership.delete` |

**Key point:** the React app *hides* buttons you can't use (`can_manage`), but that's only for UX. **The backend is the real gatekeeper**, because anyone can call the API with curl. "Never trust the client."

---

## 6. API design (REST)

- **Resources are nouns, HTTP methods are verbs:** `GET /events/`, `POST /events/`, `PATCH /events/12/`, `DELETE /events/12/`.
- **Actions on a resource are sub-resources:** `POST /events/12/rsvp/` rather than `POST /rsvpToEvent`.
- **Idempotent where it makes sense:** joining twice or volunteering twice returns 200, not an error, so a double-click never breaks anything.
- **Pagination:** lists return `{count, next, previous, results}` with 20 per page, so the API never returns an unbounded list.
- **Filtering with query params:** `?community=st-mary&upcoming=true`. You wrote the `upcoming` filter.

**Status codes used and what they mean:**
| Code | Meaning | Example |
|---|---|---|
| 200 | OK | Read, or update an existing RSVP |
| 201 | Created | New RSVP, new event |
| 204 | No content | Deleted |
| 400 | Your input is invalid | End before start, event already started |
| 401 | I don't know who you are | Missing or expired token |
| 403 | I know you, but you can't do this | A member trying to delete an event |
| 404 | Doesn't exist | `/events/999/` |
| 409 | Conflicts with current state | The event is full |
| 429 | Too many requests | Login brute force |

---

## 7. Concurrency: the last-spot race condition ([views.py → EventRSVP](../gubae/events/views.py))

**The problem:** an event has 50 spots and 49 are taken. Two people click *Going* at the same millisecond:
```
Request A: count → 49 ✓          insert → 50
Request B: count → 49 ✓                    insert → 51   ← oversold!
```
**The fix:**
```python
with transaction.atomic():
    event = Event.objects.select_for_update().get(pk=pk)   # lock this row
    going = event.rsvps.filter(status="going").count()     # count while holding the lock
    ...insert...
# lock released when the transaction commits
```
`SELECT ... FOR UPDATE` makes request B **wait** until A commits. B then counts 50 and gets **409 Full**.

- On **Postgres** this is a real row lock. **SQLite** ignores `FOR UPDATE`, but it only allows one writer at a time, so it's safe locally too.
- **Why lock the event row instead of the whole table?** Other events stay fully concurrent; only people competing for *the same* event wait.
- **Alternatives you can mention:** a `going_count` column updated with `F("going_count") + 1` plus a check constraint (optimistic, faster at huge scale), or a Redis counter for extremely hot events, like concert tickets.

The same pattern protects volunteer slots.

---

## 8. Reminders: a scheduled job ([send_reminders.py](../gubae/events/management/commands/send_reminders.py))

- Finds RSVPs that are "going" to events starting in the next 24 hours **and have `reminded_at` empty**, emails each one, then stamps `reminded_at`.
- **Idempotent:** running it 100 times sends each reminder once. That matters because schedulers sometimes run jobs twice.
- **We stamp *after* sending, so delivery is at-least-once.** If the job crashes in between, someone might get two emails. Stamping before sending would be at-most-once, where someone might get none. For reminders, a duplicate is better than a miss.
- **How it runs:** cron (`0 * * * * python manage.py send_reminders`) is enough here. At scale you'd move to **Celery + Redis** (a task queue) so that sending 10,000 emails doesn't block anything, failed sends retry, and work spreads across workers.
- **Email backend** is the console (it prints to the terminal). In production you'd switch to SMTP, SendGrid or SES with one setting.

---

## 9. Performance

**The N+1 query problem** ([views.py → `event_queryset`](../gubae/events/views.py))
A naive list of 100 events runs 1 query, plus 100 RSVP counts, plus 100+ slot queries. Our version:
- `select_related("community")` uses a SQL JOIN, so the community comes in the same query.
- `annotate(going_count=Count(...))` has the database count with GROUP BY.
- `Subquery` / `Exists` compute `my_rsvp` and `can_manage` inside the same SQL.
- `prefetch_related(volunteer_slots)` fetches all slots in one extra query.

**Result: 3 queries per page no matter how many events**, and a test (`test_list_has_no_n_plus_one`) fails if anyone breaks this.

**A real bug found during development:**
> The events list was supposed to be sorted by date via `Meta.ordering`. A pagination warning in the tests showed it wasn't sorted at all. Django **ignores `Meta.ordering` on queries with GROUP BY**, and `Count()` adds a GROUP BY. With little data it *looked* sorted by luck. I added an explicit `order_by("starts_at", "id")` (`id` breaks ties so pages are stable) and a regression test.

Other measures: the composite index on (community, starts_at), pagination, and `save(update_fields=[...])` so the reminder job writes only one column.

---

## 10. Frontend architecture ([frontend/src/](../frontend/src/))

| Piece | Job | Why this way |
|---|---|---|
| [api.ts](../frontend/src/api.ts) | Every backend call, with types | One place to attach JWTs, refresh tokens and format errors. Pages never call `fetch` directly. |
| **Auto-refresh** in `request()` | On a 401, refresh once and retry | The user stays logged in for 7 days despite 15-minute tokens |
| [auth.tsx](../frontend/src/auth.tsx) | `useAuth()`: user, login, logout | React Context avoids passing `user` through every component |
| [useLoad.ts](../frontend/src/components/useLoad.ts) | Custom hook for loading, error, data and reload | Every page needs it, so it's written once. In production: TanStack Query, which adds caching and deduping. |
| [App.tsx](../frontend/src/App.tsx) | Routes and a `RequireAuth` guard | Client-side routing; the guard is UX only, since the backend enforces access |
| **URL as state** (`?community=`) | Filter stored in the URL | Back button, refresh and shareable links all work |
| **Refetch after mutations** | RSVP, then reload the event | The server is the source of truth, because other people RSVP too |
| **TypeScript interfaces** mirror the serializers | `Event`, `Community`… | A backend field rename shows up as a compile error, not a runtime bug |
| [vite.config.ts](../frontend/vite.config.ts) proxy | `/api` goes to Django | The same origin means no CORS setup is needed in development |

---

## 11. Testing ([events/tests.py](../gubae/events/tests.py), [accounts/tests.py](../gubae/accounts/tests.py))

53 tests, each with a fresh, empty test database. They test **behavior through the API**, the way a real client would:
- **Permissions:** an admin can create; a member, an anonymous user and another community's admin can't.
- **Capacity:** a full event returns 409; cancelling frees a spot; "maybe" doesn't use a spot; someone already going can resubmit.
- **Validation:** end before start, events in the past, capacity below the current count.
- **Auth:** the password is hashed and hidden, a tampered token is rejected, refresh works, rate limiting returns 429.
- **Performance guard:** the exact query count for the events list.
- **Jobs:** reminders go only to "going" RSVPs within 24 hours, and never twice.
- **AI drafting with a mocked client:** the tests swap the real Claude client for a fake, so they check *our* logic (admin-only, defaults, refusal and no-key errors) for free and offline.
- **Reach:** members get emailed but the creator doesn't; opted-out members don't; a failed create sends nothing; calendar text is escaped, and lines fold at 75 bytes even with Amharic text.

What's missing, to say honestly: frontend tests (Vitest + React Testing Library) and a true concurrency test against Postgres.

---

## 12. Reaching people who never open the site

**The product problem:** a website only helps if people visit it. Organizers already post in WhatsApp, so asking them to *also* type events into a form creates double work, and members won't check a site every day. Two parts of the design fix this.

### 12a. Getting events IN: paste an announcement ([ai.py](../gubae/events/ai.py))
```
Admin pastes the WhatsApp text ─► POST /api/events/draft/ ─► Claude (structured JSON) ─► our checks ─► pre-filled form
                                                                                   admin reviews ─► POST /api/events/ (saves)
```
| Decision | Why |
|---|---|
| **Draft only, a human saves** | The AI can misread "next Sunday". A wrong draft costs one correction, while an auto-published wrong event misleads 300 people. |
| **Structured output (JSON schema)** | The reply is guaranteed valid JSON in exactly our shape, so there's no fragile parsing of free text. |
| **Today's date and time zone in the prompt** | So "this Sunday at 2pm" becomes a real date. |
| **Our code still validates everything** | The model only extracts. Defaults (end = start + 2h when not stated), past-date warnings and the serializer rules stay in Python. |
| **Pasted text treated as data** | It's wrapped in `<announcement>` tags in the user message and never mixed into our instructions, and the output is only a draft. That's a basic defense against prompt injection. |
| **Admin-only + 10 requests/min** | Every call costs money, so only people who can create events can spend it, and the rate limit caps abuse. |
| **Graceful failure** | With no API key, a rate limit or a refusal, the admin gets a clear message and can still fill the form by hand. The feature is optional; the core app doesn't depend on it. |
| **`effort: "low"`** | Extraction is easy, so less "thinking" means faster and cheaper answers. |
| **`fallbacks: "default"`** | If a safety filter wrongly declines a harmless announcement, the API retries on a fallback model automatically. |
| **Event + slots in one request** (`new_volunteer_slots`) | Saved in one transaction, so the announcement email already lists the volunteer needs. |

### 12b. Getting the word OUT ([notifications.py](../gubae/events/notifications.py))
**New-event email:** when an admin posts, every member with emails turned on gets one (the creator is skipped).
- Sent with `transaction.on_commit()`: **only after the save is final**. If saving fails and rolls back, nobody gets an email about an event that doesn't exist.
- `send_mass_mail` reuses one connection to the mail server for all recipients.
- **Opt-out per community** (`Membership.notify_new_events`), because people stop trusting apps that spam them.
- It runs inside the request, which is fine for a few hundred members. At thousands, move it to a Celery queue so the admin isn't waiting.

**Calendar subscription (.ics):** each community has a feed URL. A member adds it to Google or Apple Calendar **once**, and the calendar app re-downloads it periodically, so new events appear in their phone's calendar without them ever opening Gubae.
- It's **pull**, but done by the calendar app, not the person. That's the key idea.
- A stable `UID:event-<id>@gubae` means an edited event *updates* in people's calendars instead of duplicating.
- The feed is public, since calendar apps can't send a JWT. That's acceptable because events are already publicly readable. A private community would need a secret token in the URL.
- **Honest limitation:** Google Calendar refreshes subscriptions on its own schedule (often every 8–24 hours) and ignores our "refresh hourly" hint. Apple Calendar lets the user choose. For instant alerts, use the email (or later, SMS or push).
- The feed URL only works on phones once the backend is **deployed**, since a phone can't reach `localhost`.

**Live updates in the open browser tab** (spot counts changing while you watch) are a separate, optional feature: polling or WebSockets. See the scaling table below.

---

## 13. "How would you scale this?" (system design)

| If… | Then… |
|---|---|
| Real users | Postgres (already supported by environment variables), gunicorn behind nginx, HTTPS, `DEBUG=0`, a secret key from the environment |
| Lots of reads (event lists) | Cache `/events/` per community in **Redis** for 30–60 seconds; add read replicas |
| Many reminder emails | Celery workers + Redis queue, batched sends, retries |
| A viral event (10k RSVPs per minute) | Lock contention on one row becomes the bottleneck, so switch to an atomic counter (`F() + 1` with a check constraint) or a Redis counter |
| Live updates ("3 spots left!") | WebSockets (Django Channels) or polling; push the count when it changes |
| Many communities | Already multi-tenant by design: every query is scoped by community |

---

## 14. Next features

- Admin UI to promote members to admin (today it's done in the Django admin)
- Edit-event page (the API already supports `PATCH`)
- Recurring events (weekly liturgy, Bible study)
- An Ethiopian calendar display next to Gregorian dates
- Amharic interface (i18n)
- SMS or Telegram reminders for members who don't check email
- Deploy: Render or Railway for the backend plus Postgres, Vercel for the frontend

---
