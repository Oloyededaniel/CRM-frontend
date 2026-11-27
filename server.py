"""Local server for the customer management app.

Serves this folder and stores customers in data/customers.json.
The unused sign-in route still forwards a password to Microsoft and does not store it.
"""

from email.message import EmailMessage
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import threading
import time
import uuid
from pathlib import Path
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "customers.json"
LIBRARY_FILE = ROOT / "data" / "library.json"
MAIL_FILE = ROOT / "data" / "mail.json"
LOGO_DIR = ROOT / "data" / "logos"
HOST = "127.0.0.1"
PORT = 5173
STORE_LOCK = threading.Lock()
CHALLENGES = {}
CODE_TTL = 15 * 60
SESSION_TTL = 14 * 24 * 3600
CUSTOMER_FIELDS = ("name", "company", "industry", "email", "phone", "countryCode", "address", "city", "status", "notes")
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._%+\-']{0,62}[A-Za-z0-9])?"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)
EMAIL_MESSAGE = "Enter an email such as name@company.com or name@company.co.uk."
PLACES_URL = "https://photon.komoot.io/api/"
COUNTRY_CODES = (
    "GB:+44", "US:+1", "CA:+1", "IE:+353", "NG:+234", "GH:+233", "KE:+254", "ZA:+27",
    "FR:+33", "DE:+49", "NL:+31", "ES:+34", "IT:+39", "AE:+971", "IN:+91", "AU:+61", "NZ:+64",
)
STATUSES = ("Lead", "Active", "Inactive")
INDUSTRIES = (
    "Technology",
    "Financial services",
    "Healthcare",
    "Manufacturing",
    "Retail",
    "Professional services",
    "Construction",
    "Energy",
    "Transportation",
    "Aviation",
    "Hospitality",
    "Education",
    "Real estate",
    "Telecommunications",
    "Agriculture",
    "Government",
    "Nonprofit",
    "Other",
)
ROLES = (
    "HOD",
    "Director",
    "Employee Level 1",
    "Employee Level 2",
    "Employee Level 3",
    "Board",
    "MD",
    "CEO",
)
PERMISSIONS = ("Read", "User", "Admin", "Super Admin / Supervisor")
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
FULL_SCOPE = " ".join([
    "openid",
    "profile",
    "offline_access",
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/User.ReadWrite",
    "https://graph.microsoft.com/User-Phone.ReadWrite.All",
])
BASIC_SCOPE = " ".join([
    "openid",
    "profile",
    "offline_access",
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/User.ReadWrite",
])


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = parse.urlsplit(self.path).path
        if path.startswith("/data/"):
            self._json(404, {"error": "That address does not exist."})
            return
        if path == "/api/auth/session":
            self._session()
            return
        if path == "/api/auth/mail":
            self._mail_status()
            return
        if path == "/api/logo":
            self._logo()
            return
        if path == "/api/connections":
            self._connections()
            return
        if path == "/api/customers":
            account = self._require_account()
            if not account:
                return
            with STORE_LOCK:
                customers = _read_customers(account["id"])
            self._json(200, {"customers": customers})
            return
        if path == "/api/places":
            if not self._require_account():
                return
            self._suggest_places()
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "That address does not exist."})
            return
        super().do_GET()

    def do_POST(self):
        path = parse.urlsplit(self.path).path
        if path == "/api/auth/sign-up":
            self._sign_up()
            return
        if path == "/api/auth/verify":
            self._verify_sign_up()
            return
        if path == "/api/auth/sign-in":
            self._sign_in()
            return
        if path == "/api/auth/confirm":
            self._confirm_sign_in()
            return
        if path == "/api/auth/sign-out":
            self._sign_out()
            return
        if path == "/api/auth/mail":
            self._save_mail()
            return
        if path == "/api/logo":
            self._save_account_logo()
            return
        if path == "/api/connections":
            self._save_connection()
            return
        if path == "/api/connections/import":
            self._import_connection()
            return
        if path == "/api/connections/export":
            self._export_connection()
            return
        if path == "/api/customers":
            self._create_customer()
            return
        if path != "/api/sign-in":
            self._json(404, {"error": "That address does not exist."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 8000:
            self._json(400, {"error": "Sign-in details were missing or too large."})
            return
        try:
            data = json.loads(self.rfile.read(length).decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "Sign-in details were not valid."})
            return

        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        client_id = str(data.get("clientId", "")).strip()
        tenant = str(data.get("tenant", "organizations")).strip() or "organizations"
        if not username or not password or not client_id:
            self._json(400, {"error": "Enter your username, password, and the app client ID."})
            return
        if not _safe_tenant(tenant):
            self._json(400, {"error": "Tenant should be organizations or your directory id."})
            return

        body, failure = _request_token(tenant, client_id, username, password, FULL_SCOPE)
        phone_scope = True
        if failure and _phone_scope_rejected(failure):
            body, failure = _request_token(tenant, client_id, username, password, BASIC_SCOPE)
            phone_scope = False
        if failure:
            self._json(401, {"error": _friendly(failure, password)})
            return
        token = body.get("access_token")
        if not token:
            self._json(401, {"error": "Microsoft did not return an access token."})
            return
        self._json(200, {
            "access_token": token,
            "expires_in": body.get("expires_in"),
            "phone_scope": phone_scope,
        })

    def do_PUT(self):
        account = self._require_account()
        if not account:
            return
        customer_id = _customer_id(self.path)
        if not customer_id:
            self._json(404, {"error": "That customer does not exist."})
            return
        data, failure = self._read_json(20_000)
        if failure:
            self._json(400, {"error": failure})
            return
        clean, problem = _clean_customer(data)
        if problem:
            self._json(400, {"error": problem})
            return
        with STORE_LOCK:
            customers = _read_customers(account["id"])
            current = next((item for item in customers if item["id"] == customer_id), None)
            if not current:
                self._json(404, {"error": "That customer does not exist."})
                return
            sources = current.get("sources") if isinstance(current.get("sources"), dict) else {}
            current.update(clean)
            current["sources"] = sources
            _write_customers(account["id"], customers)
            syncing = dict(sources)
        shared = _sync_linked(account["id"], current, syncing)
        self._json(200, {"customer": current, "shared": shared})

    def do_DELETE(self):
        account = self._require_account()
        if not account:
            return
        customer_id = _customer_id(self.path)
        if not customer_id:
            self._json(404, {"error": "That customer does not exist."})
            return
        with STORE_LOCK:
            customers = _read_customers(account["id"])
            kept = [item for item in customers if item["id"] != customer_id]
            if len(kept) == len(customers):
                self._json(404, {"error": "That customer does not exist."})
                return
            _write_customers(account["id"], kept)
        self._json(200, {"ok": True})

    def _create_customer(self):
        account = self._require_account()
        if not account:
            return
        data, failure = self._read_json(20_000)
        if failure:
            self._json(400, {"error": failure})
            return
        clean, problem = _clean_customer(data)
        if problem:
            self._json(400, {"error": problem})
            return
        share = [str(item) for item in data.get("share", [])] if isinstance(data.get("share"), list) else []
        customer = {"id": uuid.uuid4().hex, **clean, "sources": {}}
        with STORE_LOCK:
            customers = _read_customers(account["id"])
            customers.append(customer)
            _write_customers(account["id"], customers)
        shared = []
        for platform in share:
            shared.append(_push_saved_customer(account["id"], platform, customer["id"]))
        self._json(201, {"customer": customer, "shared": shared})

    def _require_account(self):
        account = _account_from_cookie(self.headers.get("Cookie"))
        if not account:
            self._json(401, {"error": "Sign in to continue."})
            return None
        return account

    def _session(self):
        account = _account_from_cookie(self.headers.get("Cookie"))
        if not account:
            self._json(401, {"error": "Sign in to continue."})
            return
        self._json(200, {"account": _public_account(account)})

    def _mail_status(self):
        smtp_brevo = _brevo_smtp_settings()
        if smtp_brevo and smtp_brevo.get("username"):
            self._json(200, {
                "configured": bool(smtp_brevo.get("sender")),
                "provider": "brevo",
                "sender": smtp_brevo.get("sender", ""),
            })
            return
        brevo = _brevo_settings()
        if brevo:
            self._json(200, {"configured": True, "provider": "brevo", "sender": brevo["sender"]})
            return
        settings = _mail_settings()
        self._json(200, {
            "configured": bool(settings),
            "provider": "smtp" if settings else "",
            "host": settings.get("host", "") if settings else "",
            "port": settings.get("port", 587) if settings else 587,
            "username": settings.get("username", "") if settings else "",
            "sender": settings.get("sender", "") if settings else "",
        })

    def _save_mail(self):
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        api_key = str(data.get("apiKey", "")).strip()
        if api_key:
            sender = str(data.get("sender", "")).strip()
            sender_name = str(data.get("senderName", "")).strip() or "Customers"
            if not EMAIL_PATTERN.fullmatch(sender):
                self._json(400, {"error": EMAIL_MESSAGE})
                return
            _write_mail({
                "provider": "brevo",
                "apiKey": api_key,
                "sender": sender,
                "senderName": sender_name,
            })
            self._json(200, {"configured": True, "provider": "brevo"})
            return
        host = str(data.get("host", "")).strip()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        sender = str(data.get("sender", "")).strip() or username
        try:
            port = int(data.get("port") or 587)
        except (TypeError, ValueError):
            port = 0
        if not host or not username or not password or port < 1 or port > 65535:
            self._json(400, {"error": "Enter the mail server, port, username, and password."})
            return
        if not EMAIL_PATTERN.fullmatch(sender):
            self._json(400, {"error": EMAIL_MESSAGE})
            return
        _write_mail({"host": host, "port": port, "username": username, "password": password, "sender": sender})
        self._json(200, {"configured": True})

    def _sign_up(self):
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        confirm = str(data.get("confirm", ""))
        if not name or len(name) > 80:
            self._json(400, {"error": "Enter your name."})
            return
        if not EMAIL_PATTERN.fullmatch(email):
            self._json(400, {"error": EMAIL_MESSAGE})
            return
        if len(password) < 8 or len(password) > 200:
            self._json(400, {"error": "Use a password of at least 8 characters."})
            return
        if password != confirm:
            self._json(400, {"error": "The passwords do not match."})
            return
        with STORE_LOCK:
            library = _read_library()
            if any(item["email"] == email for item in library["accounts"]):
                self._json(400, {"error": "An account with that email already exists. Sign in instead."})
                return
        salt, digest = _hash_password(password)
        problem = _send_challenge(email, "signup", {
            "name": name,
            "email": email,
            "salt": salt,
            "digest": digest,
        })
        if problem:
            self._json(400, {"error": problem})
            return
        self._json(200, {"pending": True, "email": email})

    def _verify_sign_up(self):
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        email = str(data.get("email", "")).strip().lower()
        payload, problem = _take_challenge(email, "signup", str(data.get("code", "")).strip())
        if problem:
            self._json(400, {"error": problem})
            return
        with STORE_LOCK:
            library = _read_library()
            if any(item["email"] == payload["email"] for item in library["accounts"]):
                self._json(400, {"error": "An account with that email already exists. Sign in instead."})
                return
            account = {
                "id": uuid.uuid4().hex,
                "name": payload["name"],
                "email": payload["email"],
                "salt": payload["salt"],
                "digest": payload["digest"],
                "logoKind": "",
            }
            if not library["accounts"] and library.get("legacy"):
                library["customers"][account["id"]] = library.pop("legacy")
            library["accounts"].append(account)
            _write_library(library)
        self._start_session(account)

    def _sign_in(self):
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        with STORE_LOCK:
            library = _read_library()
            account = next((item for item in library["accounts"] if item["email"] == email), None)
        if not account or not _password_matches(password, account):
            self._json(401, {"error": "The email or password is not correct."})
            return
        problem = _send_challenge(email, "signin", {"email": email})
        if problem:
            self._json(400, {"error": problem})
            return
        self._json(200, {"pending": True, "email": email})

    def _confirm_sign_in(self):
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        email = str(data.get("email", "")).strip().lower()
        payload, problem = _take_challenge(email, "signin", str(data.get("code", "")).strip())
        if problem:
            self._json(400, {"error": problem})
            return
        with STORE_LOCK:
            library = _read_library()
            account = next((item for item in library["accounts"] if item["email"] == payload["email"]), None)
        if not account:
            self._json(401, {"error": "Sign in to continue."})
            return
        self._start_session(account)

    def _sign_out(self):
        token = _cookie(self.headers.get("Cookie"), "session")
        if token:
            digest = hashlib.sha256(token.encode()).hexdigest()
            with STORE_LOCK:
                library = _read_library()
                library["sessions"] = [item for item in library["sessions"] if item.get("hash") != digest]
                _write_library(library)
        self._json(200, {"ok": True}, {"Set-Cookie": "session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})

    def _start_session(self, account):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with STORE_LOCK:
            library = _read_library()
            now = time.time()
            library["sessions"] = [item for item in library["sessions"] if item.get("expires", 0) > now]
            library["sessions"].append({
                "hash": digest,
                "accountId": account["id"],
                "expires": now + SESSION_TTL,
            })
            _write_library(library)
        self._json(200, {"account": _public_account(account)}, {
            "Set-Cookie": f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}",
        })

    def _save_account_logo(self):
        account = self._require_account()
        if not account:
            return
        data, failure = self._read_json(2_500_000)
        if failure:
            self._json(400, {"error": failure})
            return
        raw, kind = _logo_bytes(data.get("logo", ""))
        if raw is None:
            self._json(400, {"error": kind})
            return
        if not raw:
            self._json(400, {"error": "Choose a logo."})
            return
        _save_logo(account["id"], raw, kind)
        with STORE_LOCK:
            library = _read_library()
            saved = next((item for item in library["accounts"] if item["id"] == account["id"]), None)
            if not saved:
                self._json(401, {"error": "Sign in to continue."})
                return
            saved["logoKind"] = kind
            _write_library(library)
        account["logoKind"] = kind
        self._json(200, {"account": _public_account(account)})

    def _logo(self):
        account = _account_from_cookie(self.headers.get("Cookie"))
        if not account or not account.get("logoKind"):
            self._json(404, {"error": "That address does not exist."})
            return
        path = LOGO_DIR / f"{account['id']}.{account['logoKind']}"
        if not path.is_file():
            self._json(404, {"error": "That address does not exist."})
            return
        raw = path.read_bytes()
        kind = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}[account["logoKind"]]
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _suggest_places(self):
        query = parse.parse_qs(parse.urlsplit(self.path).query).get("q", [""])[0]
        query = " ".join(str(query).split())
        if len(query) < 3 or len(query) > 120:
            self._json(200, {"places": []})
            return
        try:
            places = _search_places(query)
        except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            self._json(200, {"places": [], "error": "Address suggestions are unavailable. You can still type the address."})
            return
        self._json(200, {"places": places})

    def _connections(self):
        account = self._require_account()
        if not account:
            return
        saved = _account_connections(account["id"])
        self._json(200, {"platforms": [_public_platform(spec, saved.get(spec["id"])) for spec in PLATFORMS]})

    def _save_connection(self):
        account = self._require_account()
        if not account:
            return
        data, failure = self._read_json(20_000)
        if failure:
            self._json(400, {"error": failure})
            return
        platform = str(data.get("id", "")).strip()
        spec = _platform_spec(platform)
        if not spec:
            self._json(400, {"error": "Choose a platform."})
            return
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        with STORE_LOCK:
            library = _read_library()
            library.setdefault("connections", {})
            stored = library["connections"].setdefault(account["id"], {})
            current = stored.get(platform) if isinstance(stored.get(platform), dict) else {}
            merged, problem = _merge_connection(spec, current, values)
            if problem:
                self._json(400, {"error": problem})
                return
            stored[platform] = merged
            _write_library(library)
        self._json(200, {"platform": _public_platform(spec, merged)})

    def _import_connection(self):
        account = self._require_account()
        if not account:
            return
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        platform = str(data.get("id", "")).strip()
        spec = _platform_spec(platform)
        saved = _account_connections(account["id"]).get(platform)
        if not spec or not _connection_ready(spec, saved):
            self._json(400, {"error": "Save the platform details before importing customers."})
            return
        rows, problem = _pull_platform(spec["id"], saved)
        if problem:
            self._json(400, {"error": problem})
            return
        with STORE_LOCK:
            imported, updated = _merge_imported(account["id"], platform, rows)
            customers = _read_customers(account["id"])
        self._json(200, {"imported": imported, "updated": updated, "customers": customers})

    def _export_connection(self):
        account = self._require_account()
        if not account:
            return
        data, failure = self._read_json(8_000)
        if failure:
            self._json(400, {"error": failure})
            return
        result = _push_saved_customer(account["id"], str(data.get("id", "")).strip(), str(data.get("customerId", "")).strip())
        if not result.get("ok"):
            self._json(400, {"error": result.get("error") or "The customer could not be sent."})
            return
        self._json(200, {"result": result})

    def _read_json(self, limit):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > limit:
            return None, "The customer details were missing or too large."
        try:
            return json.loads(self.rfile.read(length).decode()), None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "The customer details were not valid."

    def _json(self, status, payload, headers=None):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        # Request lines only. The body, including the password, is never logged.
        super().log_message(fmt, *args)


def _safe_tenant(tenant):
    if len(tenant) > 120:
        return False
    return all(char.isalnum() or char in ".-" for char in tenant)


def _request_token(tenant, client_id, username, password, scope):
    form = parse.urlencode({
        "client_id": client_id,
        "grant_type": "password",
        "username": username,
        "password": password,
        "scope": scope,
    }).encode()
    url = TOKEN_URL.format(tenant=parse.quote(tenant))
    req = request.Request(url, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode()), None
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error_description") or parsed.get("error") or detail
        except json.JSONDecodeError:
            message = detail
        return None, str(message)
    except error.URLError as exc:
        return None, f"Could not reach Microsoft sign-in. {exc.reason}"


def _phone_scope_rejected(message):
    text = message.lower()
    return "user-phone" in text or "aadsts650053" in text


def _friendly(message, password):
    text = message.replace(password, "").replace("\r", "")
    first = text.split("\n", 1)[0].strip()
    known = (
        ("AADSTS50126", "That username or password was not accepted."),
        ("AADSTS50034", "Microsoft could not find that username in the tenant."),
        ("AADSTS50053", "The account is locked after too many attempts. Wait, then try again."),
        ("AADSTS50055", "The password is expired. Change it with Microsoft, then sign in here."),
        ("AADSTS50057", "This account is disabled."),
        ("AADSTS50076", "This account needs an extra verification step. Use Sign in with Microsoft."),
        ("AADSTS50079", "This account must register extra verification first. Use Sign in with Microsoft."),
        ("AADSTS50158", "This sign-in needs an extra security check. Use Sign in with Microsoft."),
        ("AADSTS7000218", "In the app registration, open Authentication and set Allow public client flows to Yes."),
        ("AADSTS700016", "That client ID was not found. Copy the Application (client) ID from the app registration."),
        ("AADSTS65001", "Grant consent for User.Read and User.ReadWrite on the app registration."),
        ("AADSTS650053", "Add delegated User.Read and User.ReadWrite permissions on the app registration."),
        ("AADSTS900144", "The client ID is missing."),
        ("AADSTS50059", "No tenant was found for that username."),
        ("AADSTS5000224", "Microsoft could not use that client ID with this tenant. In the setup section, set Tenant to your directory id."),
    )
    for code, plain in known:
        if code in message:
            return plain
    cleaned = re.sub(r"\s*(Trace ID:|Correlation ID:|Timestamp:).*", "", first, flags=re.IGNORECASE).strip()
    return cleaned or "Microsoft refused the sign-in."


def _customer_id(path):
    parts = [part for part in parse.urlsplit(path).path.split("/") if part]
    if len(parts) != 3 or parts[0] != "api" or parts[1] != "customers":
        return ""
    customer_id = parts[2]
    if not re.fullmatch(r"[0-9a-f]{32}", customer_id):
        return ""
    return customer_id


def _read_library():
    if LIBRARY_FILE.exists():
        try:
            data = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            data.setdefault("accounts", [])
            data.setdefault("customers", {})
            data.setdefault("sessions", [])
            data.setdefault("connections", {})
            return data
    library = {"accounts": [], "customers": {}, "sessions": [], "legacy": _legacy_customers()}
    return library


def _write_library(library):
    LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    stored = {
        "accounts": library.get("accounts", []),
        "customers": library.get("customers", {}),
        "sessions": library.get("sessions", []),
        "connections": library.get("connections", {}),
    }
    temporary = LIBRARY_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    temporary.replace(LIBRARY_FILE)


def _legacy_customers():
    if not DATA_FILE.exists():
        return []
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("id")]


def _read_customers(account_id):
    library = _read_library()
    items = library["customers"].get(account_id, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("id")]


def _write_customers(account_id, customers):
    library = _read_library()
    library["customers"][account_id] = customers
    _write_library(library)


def _cookie(header, name):
    if not header:
        return ""
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def _account_from_cookie(header):
    token = _cookie(header, "session")
    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with STORE_LOCK:
        library = _read_library()
        session = next((item for item in library["sessions"] if item.get("hash") == digest and item.get("expires", 0) > now), None)
        if not session:
            return None
        return next((item for item in library["accounts"] if item["id"] == session.get("accountId")), None)


def _public_account(account):
    return {
        "name": account["name"],
        "email": account["email"],
        "logo": bool(account.get("logoKind")),
    }


def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt, digest


def _password_matches(password, account):
    _, digest = _hash_password(password, account.get("salt"))
    return hmac.compare_digest(digest, account.get("digest", ""))


def _logo_bytes(value):
    if not value:
        return b"", ""
    text = str(value)
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        return None, "The logo file could not be read."
    if len(raw) > 1_500_000:
        return None, "The logo must be smaller than 1.5 MB."
    kind = _image_kind(raw)
    if not kind:
        return None, "Use a PNG, JPEG, WEBP, or GIF logo."
    return raw, kind


def _image_kind(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "webp"
    return ""


def _save_logo(account_id, raw, kind):
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    for existing in LOGO_DIR.glob(f"{account_id}.*"):
        existing.unlink()
    (LOGO_DIR / f"{account_id}.{kind}").write_bytes(raw)


def _load_dotenv():
    path = ROOT / ".env"
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _brevo_smtp_settings():
    _load_dotenv()
    key = os.environ.get("BREVO_SMTP_KEY", "").strip()
    if not key:
        return None
    port = os.environ.get("BREVO_SMTP_PORT", "").strip() or "587"
    try:
        port = int(port)
    except ValueError:
        port = 587
    return {
        "host": os.environ.get("BREVO_SMTP_HOST", "").strip() or "smtp-relay.brevo.com",
        "port": port,
        "username": os.environ.get("BREVO_SMTP_LOGIN", "").strip(),
        "password": key,
        "sender": os.environ.get("BREVO_SENDER", "").strip(),
        "senderName": os.environ.get("BREVO_SENDER_NAME", "").strip() or "Customers",
    }


def _brevo_settings():
    _load_dotenv()
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("BREVO_SENDER", "").strip()
    sender_name = os.environ.get("BREVO_SENDER_NAME", "").strip()
    if api_key and sender:
        return {"apiKey": api_key, "sender": sender, "senderName": sender_name or "Customers"}
    if not MAIL_FILE.exists():
        return None
    try:
        data = json.loads(MAIL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    api_key = str(data.get("apiKey", "")).strip()
    sender = str(data.get("sender", "")).strip()
    if not api_key or not sender:
        return None
    return {
        "apiKey": api_key,
        "sender": sender,
        "senderName": str(data.get("senderName", "")).strip() or "Customers",
    }


def _mail_settings():
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", "").strip()
    port = os.environ.get("SMTP_PORT", "").strip()
    if host and username and password:
        return {
            "host": host,
            "port": int(port or "587"),
            "username": username,
            "password": password,
            "sender": sender or username,
        }
    if not MAIL_FILE.exists():
        return None
    try:
        data = json.loads(MAIL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("host") or not data.get("username") or not data.get("password"):
        return None
    return data


def _write_mail(settings):
    MAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = MAIL_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temporary.replace(MAIL_FILE)


def _send_challenge(email, purpose, payload):
    key = f"{purpose}:{email}"
    current = CHALLENGES.get(key)
    if current and time.time() - current.get("sent", 0) < 30:
        return "Wait a moment before sending another code."
    code = f"{secrets.randbelow(900000) + 100000}"
    salt = secrets.token_hex(8)
    failure = _deliver_code(email, code, purpose)
    if failure:
        return failure
    CHALLENGES[key] = {
        "hash": hashlib.sha256(f"{salt}:{code}".encode()).hexdigest(),
        "salt": salt,
        "expires": time.time() + CODE_TTL,
        "attempts": 0,
        "sent": time.time(),
        "payload": payload,
    }
    return ""


def _deliver_code(recipient, code, purpose):
    smtp_brevo = _brevo_smtp_settings()
    if smtp_brevo:
        if not smtp_brevo.get("username"):
            return "Set BREVO_SMTP_LOGIN in .env to the Brevo SMTP login."
        if not smtp_brevo.get("sender"):
            return "Set BREVO_SENDER in .env to an address you verified in Brevo."
        return _send_code(smtp_brevo, recipient, code, purpose)
    brevo = _brevo_settings()
    if brevo:
        return _send_via_brevo(brevo, recipient, code, purpose)
    settings = _mail_settings()
    if settings:
        return _send_code(settings, recipient, code, purpose)
    return "Add the Brevo SMTP key and a verified sender address before a code can be emailed."


def _send_via_brevo(settings, recipient, code, purpose):
    action = "create your account" if purpose == "signup" else "sign in"
    payload = {
        "sender": {"email": settings["sender"], "name": settings.get("senderName") or "Customers"},
        "to": [{"email": recipient}],
        "subject": "Your verification code",
        "textContent": (
            f"Your code to {action} is {code}.\n\n"
            "It is valid for 15 minutes. If you did not request this code, you can ignore this email.\n"
        ),
    }
    req = request.Request("https://api.brevo.com/v3/smtp/email", data=json.dumps(payload).encode(), method="POST")
    req.add_header("accept", "application/json")
    req.add_header("content-type", "application/json")
    req.add_header("api-key", settings["apiKey"])
    try:
        with request.urlopen(req, timeout=20) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return _brevo_failure(exc.code, detail)
    except (OSError, TimeoutError, error.URLError):
        return "The code could not be emailed. Check the internet connection and try again."
    return ""


def _brevo_failure(status, detail):
    text = detail.lower()
    if status == 401:
        return "Brevo refused the API key. Check it and try again."
    if status == 400 and "sender" in text:
        return "Brevo refused the sender address. Verify that address in Brevo, then try again."
    return "The code could not be emailed through Brevo. Try again."


def _take_challenge(email, purpose, code):
    key = f"{purpose}:{email}"
    item = CHALLENGES.get(key)
    if not item or item["expires"] < time.time():
        CHALLENGES.pop(key, None)
        return None, "That code has expired. Send a new one."
    if not re.fullmatch(r"[0-9]{6}", code):
        return None, "Enter the 6-digit code from your email."
    if item["attempts"] >= 5:
        CHALLENGES.pop(key, None)
        return None, "Too many attempts. Send a new code."
    digest = hashlib.sha256(f"{item['salt']}:{code}".encode()).hexdigest()
    if not hmac.compare_digest(digest, item["hash"]):
        item["attempts"] += 1
        return None, "That code is not correct."
    CHALLENGES.pop(key, None)
    return item["payload"], ""


def _send_code(settings, recipient, code, purpose):
    action = "create your account" if purpose == "signup" else "sign in"
    message = EmailMessage()
    message["Subject"] = "Your verification code"
    sender = settings.get("sender") or settings["username"]
    sender_name = str(settings.get("senderName") or "").strip()
    message["From"] = f"{sender_name} <{sender}>" if sender_name else sender
    message["To"] = recipient
    message.set_content(
        f"Your code to {action} is {code}.\n\n"
        "It is valid for 15 minutes. If you did not request this code, you can ignore this email.\n"
    )
    try:
        with smtplib.SMTP(settings["host"], int(settings["port"]), timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        return "Brevo refused the SMTP key. Check it and try again."
    except smtplib.SMTPException as exc:
        text = str(exc).lower()
        if "sender" in text or "from" in text:
            return "Brevo refused the sender address. Verify that address in Brevo, then try again."
        return "The code could not be emailed. Check the outgoing mail account and try again."
    except (OSError, ValueError):
        return "The code could not be emailed. Check the internet connection and try again."
    return ""


def _text(value):
    return "" if value is None else str(value).strip()


def _place_label(props):
    house = _text(props.get("housenumber"))
    street = _text(props.get("street"))
    name = _text(props.get("name"))
    if house and street:
        line = f"{house} {street}"
    elif street and name and name.casefold() not in street.casefold():
        line = name
    else:
        line = street or name
    city = _text(props.get("city") or props.get("town") or props.get("village") or props.get("district"))
    parts = []
    for part in (line, city, _text(props.get("postcode")), _text(props.get("state")), _text(props.get("country"))):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts)[:200], city[:120]


def _search_places(query):
    params = parse.urlencode({"q": query, "limit": 6, "lang": "en", "lat": "54.78", "lon": "-1.57"})
    req = request.Request(
        f"{PLACES_URL}?{params}",
        headers={
            "User-Agent": "CompanyRecords/1.0 (local customer form)",
            "Accept": "application/json",
        },
    )
    with request.urlopen(req, timeout=6) as response:
        payload = json.loads(response.read().decode())
    places = []
    seen = set()
    for feature in payload.get("features") or []:
        label, city = _place_label(feature.get("properties") or {})
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        places.append({"label": label, "city": city})
    return places


def _clean_customer(data):
    if not isinstance(data, dict):
        return None, "The customer details were not valid."
    clean = {}
    for key in CUSTOMER_FIELDS:
        value = data.get(key, "")
        clean[key] = "" if value is None else str(value).strip()
    if not clean["name"]:
        return None, "Enter the owner's name."
    if len(clean["name"]) > 120:
        return None, "The owner's name is too long."
    for key in ("company", "email", "phone", "city"):
        if len(clean[key]) > 120:
            return None, "One of the customer fields is too long."
    if len(clean["address"]) > 200:
        return None, "The address is too long."
    if len(clean["notes"]) > 2000:
        return None, "The notes are too long."
    if clean["email"] and not EMAIL_PATTERN.fullmatch(clean["email"]):
        return None, EMAIL_MESSAGE
    if clean["phone"]:
        if not re.fullmatch(r"[0-9]{6,15}", clean["phone"]):
            return None, "Phone number must be 6 to 15 digits, with no letters or spaces."
        if clean["countryCode"] not in COUNTRY_CODES:
            return None, "Choose a country code for the phone number."
    else:
        clean["countryCode"] = ""
    if clean["status"] not in STATUSES:
        clean["status"] = "Lead"
    if clean["industry"] not in INDUSTRIES:
        clean["industry"] = ""
    employees, problem = _clean_employees(data.get("employees"))
    if problem:
        return None, problem
    clean["employees"] = employees
    return clean, None


def _clean_employees(raw):
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "The employee list was not valid."
    if len(raw) > 40:
        return None, "A customer can have at most 40 employees."
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            return None, "An employee record was not valid."
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or "").strip()
        permission = str(item.get("permission") or "").strip()
        if not name:
            return None, "Enter a name for each employee."
        if len(name) > 120:
            return None, "An employee name is too long."
        if role not in ROLES:
            return None, "Choose a role for each employee."
        if permission not in PERMISSIONS:
            return None, "Choose a permission for each employee."
        employee_id = str(item.get("id") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", employee_id):
            employee_id = uuid.uuid4().hex
        contact = str(item.get("contact") or "").strip().lower()
        email = str(item.get("email") or "").strip()
        phone = re.sub(r"\D", "", str(item.get("phone") or ""))
        country = str(item.get("countryCode") or "").strip()
        if contact not in ("email", "phone"):
            return None, "Choose email or phone for each employee."
        if contact == "email":
            if not EMAIL_PATTERN.fullmatch(email):
                return None, "Enter an employee email such as name@company.com or name@company.co.uk."
            phone = ""
            country = ""
        else:
            if not re.fullmatch(r"[0-9]{6,15}", phone):
                return None, "Employee phone number must be 6 to 15 digits, with no letters or spaces."
            if country not in COUNTRY_CODES:
                return None, "Choose a country code for each employee phone number."
            email = ""
        cleaned.append({
            "id": employee_id,
            "name": name,
            "role": role,
            "permission": permission,
            "contact": contact,
            "email": email,
            "phone": phone,
            "countryCode": country,
        })
    return cleaned, None


PLATFORMS = (
    {
        "id": "graph",
        "name": "Microsoft Graph and SharePoint",
        "detail": "Uses an Entra app registration. A SharePoint site imports the list named in List name. Without a site, organization contacts are imported.",
        "fields": (
            {"key": "tenantId", "label": "Tenant ID"},
            {"key": "clientId", "label": "Client ID"},
            {"key": "clientSecret", "label": "Client secret", "secret": True},
            {"key": "site", "label": "SharePoint site URL", "optional": True},
            {"key": "listName", "label": "SharePoint list name", "optional": True},
        ),
    },
    {
        "id": "nable",
        "name": "N-able N-central",
        "detail": "Uses the N-central server address and a user API token. Customers already in N-central can be imported, and a new customer can be sent back.",
        "fields": (
            {"key": "baseUrl", "label": "Server URL"},
            {"key": "apiKey", "label": "API token", "secret": True},
        ),
    },
    {
        "id": "hubspot",
        "name": "HubSpot",
        "detail": "Uses a private app token. Companies in HubSpot are the customers.",
        "fields": (
            {"key": "token", "label": "Private app token", "secret": True},
        ),
    },
    {
        "id": "connectwise",
        "name": "ConnectWise Manage",
        "detail": "Uses the API site, company id, public and private keys, and the ConnectWise client ID.",
        "fields": (
            {"key": "site", "label": "API site URL"},
            {"key": "company", "label": "Company ID"},
            {"key": "publicKey", "label": "Public key"},
            {"key": "privateKey", "label": "Private key", "secret": True},
            {"key": "clientId", "label": "Client ID"},
        ),
    },
    {
        "id": "salesforce",
        "name": "Salesforce",
        "detail": "Uses a connected app with the client-credentials flow. Accounts are the customers.",
        "fields": (
            {"key": "domain", "label": "Login domain"},
            {"key": "clientId", "label": "Client ID"},
            {"key": "clientSecret", "label": "Client secret", "secret": True},
        ),
    },
)


def _platform_spec(platform):
    return next((item for item in PLATFORMS if item["id"] == platform), None)


def _account_connections(account_id):
    library = _read_library()
    saved = library.get("connections", {}).get(account_id, {})
    return saved if isinstance(saved, dict) else {}


def _public_platform(spec, saved):
    saved = saved if isinstance(saved, dict) else {}
    values = {}
    secrets = {}
    for field in spec["fields"]:
        if field.get("secret"):
            secrets[field["key"]] = bool(saved.get(field["key"]))
        else:
            values[field["key"]] = str(saved.get(field["key"]) or "")
    return {
        "id": spec["id"],
        "name": spec["name"],
        "detail": spec["detail"],
        "fields": [{"key": field["key"], "label": field["label"], "secret": bool(field.get("secret")), "optional": bool(field.get("optional"))} for field in spec["fields"]],
        "values": values,
        "secrets": secrets,
        "ready": _connection_ready(spec, saved),
    }


def _connection_ready(spec, saved):
    if not isinstance(saved, dict):
        return False
    return all(str(saved.get(field["key"]) or "").strip() for field in spec["fields"] if not field.get("optional"))


def _merge_connection(spec, current, incoming):
    merged = {}
    for field in spec["fields"]:
        key = field["key"]
        value = str(incoming.get(key) or "").strip()
        if field.get("secret") and not value:
            value = str(current.get(key) or "")
        if len(value) > 500:
            return None, f"{field['label']} is too long."
        if not field.get("optional") and not value:
            return None, f"Enter the {field['label']}."
        merged[key] = value
    if spec["id"] == "nable" and not _service_base(merged.get("baseUrl", "")):
        return None, "Enter a server address that starts with http:// or https://."
    if spec["id"] == "connectwise" and not _service_base(merged.get("site", "")):
        return None, "Enter an API site address that starts with http:// or https://."
    if spec["id"] == "graph" and merged.get("site") and not _service_base(merged["site"]):
        return None, "Enter a SharePoint site address that starts with http:// or https://."
    if spec["id"] == "salesforce":
        domain = merged.get("domain", "").replace("https://", "").replace("http://", "").strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", domain):
            return None, "Enter the Salesforce domain, such as login.salesforce.com."
        merged["domain"] = domain
    return merged, None


def _service_base(value):
    parsed = parse.urlsplit(value.strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.hostname}{port}{path}"


def _http_json(url, method="GET", payload=None, headers=None, form=None):
    data = None
    hdrs = {"Accept": "application/json", "User-Agent": "CompanyRecords/1.0"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with request.urlopen(req, timeout=25) as response:
            raw = response.read().decode()
            return (json.loads(raw) if raw else {}), None
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return None, _platform_error(exc.code, detail)
    except (OSError, TimeoutError, error.URLError, json.JSONDecodeError):
        return None, "The platform could not be reached. Check the address and try again."


def _platform_error(status, detail):
    message = ""
    try:
        body = json.loads(detail)
        if isinstance(body, dict):
            message = str(body.get("message") or body.get("error_description") or body.get("error") or "")
            nested = body.get("error")
            if isinstance(nested, dict):
                message = str(nested.get("message") or message)
    except json.JSONDecodeError:
        message = ""
    message = re.sub(r"\s+", " ", message).strip()[:240]
    if status in (401, 403):
        return message or "The platform refused the keys. Check the client ID, tenant, and secret."
    return message or "The platform rejected the request."


def _rows_of(payload, *keys):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _phone_digits(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if re.fullmatch(r"[0-9]{6,15}", digits) else ""


def _row(external_id, name, company="", email="", phone="", address="", city="", industry=""):
    name = str(name or company or "").strip()
    email = str(email or "").strip()
    if email and not EMAIL_PATTERN.fullmatch(email):
        email = ""
    return {
        "externalId": str(external_id or "").strip(),
        "name": name[:120],
        "company": str(company or "").strip()[:120],
        "email": email[:120],
        "phone": _phone_digits(phone),
        "address": str(address or "").strip()[:200],
        "city": str(city or "").strip()[:120],
        "industry": _local_industry(industry),
    }


def _pull_platform(platform, saved):
    if platform == "graph":
        return _pull_graph(saved)
    if platform == "nable":
        return _pull_nable(saved)
    if platform == "hubspot":
        return _pull_hubspot(saved)
    if platform == "connectwise":
        return _pull_connectwise(saved)
    if platform == "salesforce":
        return _pull_salesforce(saved)
    return None, "Choose a platform."


def _push_platform(platform, saved, customer):
    if platform == "graph":
        return _push_graph(saved, customer)
    if platform == "nable":
        return _push_nable(saved, customer)
    if platform == "hubspot":
        return _push_hubspot(saved, customer)
    if platform == "connectwise":
        return _push_connectwise(saved, customer)
    if platform == "salesforce":
        return _push_salesforce(saved, customer)
    return None, "Choose a platform."


def _graph_token(saved):
    tenant = parse.quote(saved["tenantId"], safe="")
    body, failure = _http_json(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "POST",
        form={
            "client_id": saved["clientId"],
            "client_secret": saved["clientSecret"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
    )
    if failure:
        return None, failure
    token = body.get("access_token")
    if not token:
        return None, "Microsoft did not return an access token."
    return token, None


def _graph_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _graph_site(token, site):
    parsed = parse.urlsplit(site.strip())
    path = parsed.path.rstrip("/")
    target = f"{parsed.hostname}:{path}" if path else parsed.hostname
    body, failure = _http_json(f"https://graph.microsoft.com/v1.0/sites/{target}", headers=_graph_headers(token))
    if failure:
        return None, failure
    return body.get("id"), None


def _pull_graph(saved):
    token, failure = _graph_token(saved)
    if failure:
        return None, failure
    if saved.get("site"):
        return _pull_sharepoint(token, saved)
    body, failure = _http_json(
        "https://graph.microsoft.com/v1.0/contacts?$top=200&$select=id,displayName,companyName,emailAddresses,businessPhones,businessAddress",
        headers=_graph_headers(token),
    )
    if failure:
        return None, failure
    rows = []
    for item in _rows_of(body, "value"):
        emails = item.get("emailAddresses") or []
        phones = item.get("businessPhones") or []
        address = item.get("businessAddress") or {}
        rows.append(_row(
            item.get("id"),
            item.get("displayName"),
            item.get("companyName"),
            (emails[0] or {}).get("address") if emails else "",
            phones[0] if phones else "",
            address.get("street"),
            address.get("city"),
        ))
    return [row for row in rows if row["externalId"] and row["name"]], None


def _pull_sharepoint(token, saved):
    site_id, failure = _graph_site(token, saved["site"])
    if failure:
        return None, failure
    list_name = saved.get("listName") or "Customers"
    listed, failure = _http_json(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists?$filter=displayName eq '{list_name.replace(chr(39), chr(39) * 2)}'",
        headers=_graph_headers(token),
    )
    if failure:
        return None, failure
    lists = _rows_of(listed, "value")
    if not lists:
        return None, f"No SharePoint list named {list_name} was found on that site."
    items, failure = _http_json(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{lists[0]['id']}/items?$expand=fields&$top=200",
        headers=_graph_headers(token),
    )
    if failure:
        return None, failure
    rows = []
    for item in _rows_of(items, "value"):
        fields = item.get("fields") or {}
        rows.append(_row(
            item.get("id"),
            fields.get("Title") or fields.get("Name") or fields.get("Company"),
            fields.get("Company") or fields.get("CompanyName"),
            fields.get("Email") or fields.get("WorkEmail"),
            fields.get("Phone") or fields.get("WorkPhone"),
            fields.get("Address") or fields.get("WorkAddress"),
            fields.get("City"),
        ))
    return [row for row in rows if row["externalId"] and row["name"]], None


def _push_graph(saved, customer):
    token, failure = _graph_token(saved)
    if failure:
        return None, failure
    if saved.get("site"):
        return _push_sharepoint(token, saved, customer)
    body, failure = _http_json(
        "https://graph.microsoft.com/v1.0/contacts",
        "POST",
        {
            "displayName": customer["name"],
            "companyName": customer.get("company") or customer["name"],
            "emailAddresses": [{"address": customer["email"]}] if customer.get("email") else [],
            "businessPhones": [customer["phone"]] if customer.get("phone") else [],
        },
        _graph_headers(token),
    )
    if failure:
        return None, failure
    return str(body.get("id") or ""), None


def _push_sharepoint(token, saved, customer):
    site_id, failure = _graph_site(token, saved["site"])
    if failure:
        return None, failure
    list_name = saved.get("listName") or "Customers"
    listed, failure = _http_json(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists?$filter=displayName eq '{list_name.replace(chr(39), chr(39) * 2)}'",
        headers=_graph_headers(token),
    )
    if failure:
        return None, failure
    lists = _rows_of(listed, "value")
    if not lists:
        return None, f"No SharePoint list named {list_name} was found on that site."
    fields = {"Title": customer["name"]}
    for key, source in (("Email", "email"), ("Phone", "phone"), ("Company", "company"), ("Address", "address"), ("City", "city")):
        if customer.get(source):
            fields[key] = customer[source]
    body, failure = _http_json(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{lists[0]['id']}/items",
        "POST",
        {"fields": fields},
        _graph_headers(token),
    )
    if failure:
        body, failure = _http_json(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{lists[0]['id']}/items",
            "POST",
            {"fields": {"Title": customer["name"]}},
            _graph_headers(token),
        )
    if failure:
        return None, failure
    return str(body.get("id") or ""), None


def _pull_nable(saved):
    base = _service_base(saved["baseUrl"])
    body, failure = _http_json(f"{base}/api/customers?pageSize=200", headers={"Authorization": f"Bearer {saved['apiKey']}"})
    if failure:
        return None, failure
    rows = []
    for item in _rows_of(body, "data", "customers", "items"):
        rows.append(_row(
            item.get("customerId") or item.get("id"),
            item.get("customerName") or item.get("name"),
            item.get("customerName") or item.get("name"),
            item.get("contactEmail") or item.get("email"),
            item.get("phone") or item.get("phoneNumber"),
            item.get("address") or item.get("street"),
            item.get("city"),
        ))
    return [row for row in rows if row["externalId"] and row["name"]], None


def _push_nable(saved, customer):
    base = _service_base(saved["baseUrl"])
    body, failure = _http_json(
        f"{base}/api/customers",
        "POST",
        {
            "customerName": customer.get("company") or customer["name"],
            "contactEmail": customer.get("email") or "",
            "phone": customer.get("phone") or "",
            "city": customer.get("city") or "",
        },
        {"Authorization": f"Bearer {saved['apiKey']}"},
    )
    if failure:
        return None, failure
    return str(body.get("customerId") or body.get("id") or ""), None


HUBSPOT_INDUSTRY = {
    "Technology": "INFORMATION_TECHNOLOGY_AND_SERVICES",
    "Financial services": "FINANCIAL_SERVICES",
    "Healthcare": "HOSPITAL_HEALTH_CARE",
    "Manufacturing": "MECHANICAL_OR_INDUSTRIAL_ENGINEERING",
    "Retail": "RETAIL",
    "Professional services": "MANAGEMENT_CONSULTING",
    "Construction": "CONSTRUCTION",
    "Energy": "OIL_ENERGY",
    "Transportation": "TRANSPORTATION_TRUCKING_RAILROAD",
    "Aviation": "AIRLINES_AVIATION",
    "Hospitality": "HOSPITALITY",
    "Education": "EDUCATION_MANAGEMENT",
    "Real estate": "REAL_ESTATE",
    "Telecommunications": "TELECOMMUNICATIONS",
    "Agriculture": "FARMING",
    "Government": "GOVERNMENT_ADMINISTRATION",
    "Nonprofit": "NON_PROFIT_ORGANIZATION_MANAGEMENT",
}
HUBSPOT_INDUSTRY_FROM = {value: label for label, value in HUBSPOT_INDUSTRY.items()}
HUBSPOT_INDUSTRY_FROM["AVIATION_AEROSPACE"] = "Aviation"
HUBSPOT_INDUSTRY_FROM["COMPUTER_SOFTWARE"] = "Technology"


def _local_industry(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text in INDUSTRIES:
        return text
    key = re.sub(r"[^A-Z0-9]+", "_", text.upper().replace("&", " AND ")).strip("_")
    if key in HUBSPOT_INDUSTRY_FROM:
        return HUBSPOT_INDUSTRY_FROM[key]
    if "AVIATION" in key or "AIRLINE" in key:
        return "Aviation"
    return ""


def _hubspot_industry(value):
    label = _local_industry(value)
    return HUBSPOT_INDUSTRY.get(label, "")


def _hubspot_headers(saved):
    return {"Authorization": f"Bearer {saved['token']}"}


def _hubspot_company_properties(customer):
    properties = {
        "name": customer.get("company") or customer["name"],
        "phone": customer.get("phone") or "",
        "city": customer.get("city") or "",
        "address": customer.get("address") or "",
    }
    industry = _hubspot_industry(customer.get("industry"))
    if industry:
        properties["industry"] = industry
    return properties


def _sync_hubspot_owner(saved, company_id, owner):
    owner = str(owner or "").strip()
    if not owner or not company_id:
        return None
    first, _, last = owner.partition(" ")
    headers = _hubspot_headers(saved)
    listed, failure = _http_json(
        f"https://api.hubapi.com/crm/v4/objects/companies/{parse.quote(company_id)}/associations/contacts",
        headers=headers,
    )
    if failure:
        return _hubspot_owner_failure(failure)
    contact_id = ""
    for item in _rows_of(listed, "results"):
        contact_id = str(item.get("toObjectId") or item.get("id") or "")
        if contact_id:
            break
    properties = {"firstname": first, "lastname": last}
    if contact_id:
        _, failure = _http_json(
            f"https://api.hubapi.com/crm/v3/objects/contacts/{parse.quote(contact_id)}",
            "PATCH",
            {"properties": properties},
            headers,
        )
        return _hubspot_owner_failure(failure) if failure else None
    created, failure = _http_json(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        "POST",
        {"properties": properties},
        headers,
    )
    if failure:
        return _hubspot_owner_failure(failure)
    contact_id = str((created or {}).get("id") or "")
    if not contact_id:
        return "HubSpot did not return the owner contact."
    _, failure = _http_json(
        f"https://api.hubapi.com/crm/v3/objects/contacts/{parse.quote(contact_id)}/associations/companies/{parse.quote(company_id)}/1",
        "PUT",
        headers=headers,
    )
    return _hubspot_owner_failure(failure) if failure else None


def _hubspot_owner_failure(failure):
    if not failure:
        return None
    text = failure.lower()
    if "scope" in text or "permission" in text or "not authorized" in text:
        return "The company was saved in HubSpot. Add crm.objects.contacts.read and crm.objects.contacts.write to the service key to update the owner name there."
    return failure


def _pull_hubspot(saved):
    body, failure = _http_json(
        "https://api.hubapi.com/crm/v3/objects/companies?limit=100&properties=name,phone,city,address,domain,industry",
        headers=_hubspot_headers(saved),
    )
    if failure:
        return None, failure
    rows = []
    for item in _rows_of(body, "results"):
        props = item.get("properties") or {}
        rows.append(_row(
            item.get("id"),
            props.get("name"),
            props.get("name"),
            "",
            props.get("phone"),
            props.get("address"),
            props.get("city"),
            props.get("industry"),
        ))
    return [row for row in rows if row["externalId"] and row["name"]], None


def _push_hubspot(saved, customer):
    body, failure = _http_json(
        "https://api.hubapi.com/crm/v3/objects/companies",
        "POST",
        {"properties": _hubspot_company_properties(customer)},
        _hubspot_headers(saved),
    )
    if failure:
        return None, failure
    company_id = str(body.get("id") or "")
    owner_failure = _sync_hubspot_owner(saved, company_id, customer.get("name"))
    return company_id, owner_failure


def _update_hubspot(saved, customer, company_id):
    _, failure = _http_json(
        f"https://api.hubapi.com/crm/v3/objects/companies/{parse.quote(str(company_id))}",
        "PATCH",
        {"properties": _hubspot_company_properties(customer)},
        _hubspot_headers(saved),
    )
    if failure:
        return failure
    return _sync_hubspot_owner(saved, company_id, customer.get("name"))


def _connectwise_headers(saved):
    raw = f"{saved['company']}+{saved['publicKey']}:{saved['privateKey']}".encode()
    return {
        "Authorization": f"Basic {base64.b64encode(raw).decode()}",
        "clientId": saved["clientId"],
    }


def _pull_connectwise(saved):
    base = _service_base(saved["site"])
    body, failure = _http_json(
        f"{base}/v4_6_release/apis/3.0/company/companies?pageSize=200&fields=id,name,phoneNumber,city,addressLine1",
        headers=_connectwise_headers(saved),
    )
    if failure:
        return None, failure
    rows = []
    for item in _rows_of(body):
        rows.append(_row(item.get("id"), item.get("name"), item.get("name"), "", item.get("phoneNumber"), item.get("addressLine1"), item.get("city")))
    return [row for row in rows if row["externalId"] and row["name"]], None


def _push_connectwise(saved, customer):
    base = _service_base(saved["site"])
    name = customer.get("company") or customer["name"]
    identifier = re.sub(r"[^A-Za-z0-9]", "", name)[:30] or "CUSTOMER"
    body, failure = _http_json(
        f"{base}/v4_6_release/apis/3.0/company/companies",
        "POST",
        {
            "name": name,
            "identifier": identifier,
            "phoneNumber": customer.get("phone") or "",
            "city": customer.get("city") or "",
            "addressLine1": customer.get("address") or "",
        },
        _connectwise_headers(saved),
    )
    if failure:
        return None, failure
    return str(body.get("id") or ""), None


def _salesforce_token(saved):
    body, failure = _http_json(
        f"https://{saved['domain']}/services/oauth2/token",
        "POST",
        form={
            "grant_type": "client_credentials",
            "client_id": saved["clientId"],
            "client_secret": saved["clientSecret"],
        },
    )
    if failure:
        return None, None, failure
    token = body.get("access_token")
    instance = body.get("instance_url")
    if not token or not instance:
        return None, None, "Salesforce did not return an access token."
    return token, instance, None


def _pull_salesforce(saved):
    token, instance, failure = _salesforce_token(saved)
    if failure:
        return None, failure
    query = parse.quote("SELECT Id, Name, Phone, BillingCity, BillingStreet FROM Account")
    body, failure = _http_json(
        f"{instance}/services/data/v59.0/query?q={query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if failure:
        return None, failure
    rows = []
    for item in _rows_of(body, "records"):
        rows.append(_row(item.get("Id"), item.get("Name"), item.get("Name"), "", item.get("Phone"), item.get("BillingStreet"), item.get("BillingCity")))
    return [row for row in rows if row["externalId"] and row["name"]], None


def _push_salesforce(saved, customer):
    token, instance, failure = _salesforce_token(saved)
    if failure:
        return None, failure
    body, failure = _http_json(
        f"{instance}/services/data/v59.0/sobjects/Account",
        "POST",
        {
            "Name": customer.get("company") or customer["name"],
            "Phone": customer.get("phone") or "",
            "BillingCity": customer.get("city") or "",
            "BillingStreet": customer.get("address") or "",
        },
        {"Authorization": f"Bearer {token}"},
    )
    if failure:
        return None, failure
    return str(body.get("id") or ""), None


def _merge_imported(account_id, platform, rows):
    customers = _read_customers(account_id)
    imported = 0
    updated = 0
    for row in rows:
        current = next((item for item in customers if str((item.get("sources") or {}).get(platform) or "") == row["externalId"]), None)
        if current is None and row["email"]:
            current = next((item for item in customers if str(item.get("email") or "").lower() == row["email"].lower()), None)
        if current:
            for key in ("company", "email", "phone", "address", "city"):
                if row[key] and not current.get(key):
                    current[key] = row[key]
            if row.get("industry"):
                current["industry"] = row["industry"]
            current.setdefault("sources", {})
            current["sources"][platform] = row["externalId"]
            updated += 1
            continue
        customers.append({
            "id": uuid.uuid4().hex,
            "name": row["name"],
            "company": row["company"],
            "industry": row.get("industry") or "",
            "email": row["email"],
            "phone": row["phone"],
            "countryCode": "",
            "address": row["address"],
            "city": row["city"],
            "status": "Active",
            "notes": "",
            "employees": [],
            "sources": {platform: row["externalId"]},
        })
        imported += 1
    _write_customers(account_id, customers)
    return imported, updated


def _sync_linked(account_id, customer, sources):
    shared = []
    for platform, external in sources.items():
        if platform != "hubspot" or not external:
            continue
        spec = _platform_spec(platform)
        saved = _account_connections(account_id).get(platform)
        if not spec or not _connection_ready(spec, saved):
            continue
        failure = _update_hubspot(saved, customer, external)
        shared.append({"id": platform, "name": spec["name"], "ok": not failure, "error": failure or ""})
    return shared


def _push_saved_customer(account_id, platform, customer_id):
    spec = _platform_spec(platform)
    saved = _account_connections(account_id).get(platform) if spec else None
    name = spec["name"] if spec else platform
    if not spec or not _connection_ready(spec, saved):
        return {"id": platform, "name": name, "ok": False, "error": "Save the platform details first."}
    with STORE_LOCK:
        customer = next((item for item in _read_customers(account_id) if item["id"] == customer_id), None)
    if not customer:
        return {"id": platform, "name": name, "ok": False, "error": "That customer does not exist."}
    external, failure = _push_platform(platform, saved, customer)
    if external:
        with STORE_LOCK:
            customers = _read_customers(account_id)
            current = next((item for item in customers if item["id"] == customer_id), None)
            if current:
                current.setdefault("sources", {})
                current["sources"][platform] = external
                _write_customers(account_id, customers)
                customer = current
    if failure:
        return {"id": platform, "name": name, "ok": False, "error": failure, "customer": customer}
    return {"id": platform, "name": name, "ok": True, "customer": customer}


def main():
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Customers: http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
