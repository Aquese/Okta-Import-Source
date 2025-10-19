import os
import time
import urllib.parse
import requests
import pandas as pd
from dotenv import load_dotenv

# ----------------------------
# Setup
# ----------------------------
load_dotenv()
OKTA_DOMAIN = os.getenv("OKTA_DOMAIN", "").strip().rstrip("/")
OKTA_TOKEN = os.getenv("OKTA_API_TOKEN")
BOB_APP_ID = os.getenv("BOB_APP_ID")           # Preferred if you know it
BOB_APP_LABEL = os.getenv("BOB_APP_LABEL")     # e.g., "HiBob" or your "bob" app label

if not OKTA_DOMAIN or not OKTA_TOKEN:
    raise ValueError("Missing OKTA_DOMAIN or OKTA_API_TOKEN in .env file")

# Normalize domain to include scheme
if not OKTA_DOMAIN.startswith("http://") and not OKTA_DOMAIN.startswith("https://"):
    OKTA_DOMAIN = f"https://{OKTA_DOMAIN}"

headers = {
    "Authorization": f"SSWS {OKTA_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "okta-report-bob-origin/1.0"
}

SESSION = requests.Session()
SESSION.headers.update(headers)
TIMEOUT = 30


def _sleep_for_rate_limit(resp):
    # basic 429 handling
    if resp.status_code != 429:
        return False
    reset = resp.headers.get("x-rate-limit-reset")
    if reset and reset.isdigit():
        # sleep until reset + small buffer
        sleep_s = max(int(reset) - int(time.time()) + 1, 2)
    else:
        sleep_s = 2
    time.sleep(sleep_s)
    return True


def _get(url):
    """GET with simple 429 retry."""
    while True:
        resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 429:
            if _sleep_for_rate_limit(resp):
                continue
        return resp


def _get_paginated(url):
    """Follow Okta Link headers to accumulate lists."""
    items = []
    while url:
        resp = _get(url)
        if resp.status_code != 200:
            raise Exception(f"GET {url} -> {resp.status_code} {resp.text}")
        data = resp.json()
        if isinstance(data, list):
            items.extend(data)
        else:
            items.append(data)

        next_url = None
        link = resp.headers.get("link") or resp.headers.get("Link")
        if link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    next_url = part[part.find("<") + 1: part.find(">")]
                    break
        url = next_url
    return items


def resolve_bob_app_id():
    """Return bob appId from env or by label search."""
    if BOB_APP_ID:
        return BOB_APP_ID

    if not BOB_APP_LABEL:
        raise ValueError(
            "Set BOB_APP_ID or BOB_APP_LABEL in your .env to identify the 'bob' app"
        )

    q = urllib.parse.quote(BOB_APP_LABEL)
    url = f"{OKTA_DOMAIN}/api/v1/apps?q={q}&limit=200"
    apps = _get_paginated(url)

    # Prefer exact (case-insensitive) label match
    for app in apps:
        if app.get("label", "").lower() == BOB_APP_LABEL.lower():
            return app["id"]

    # Fallback: any label containing 'bob'
    for app in apps:
        if "bob" in app.get("label", "").lower():
            return app["id"]

    raise ValueError(
        f"Could not find a bob app by label '{BOB_APP_LABEL}'. "
        f"Set BOB_APP_ID to the exact application ID."
    )


def collect_okta_users():
    url = f"{OKTA_DOMAIN}/api/v1/users?limit=200"
    return _get_paginated(url)


def collect_bob_user_ids(bob_app_id):
    """
    Build a set of Okta user IDs that exist as App Users under the bob application.
    This uses the 'users' link off the app and parses the userId from _links.user.href
    to avoid an extra per-user call.
    """
    user_ids = set()
    url = f"{OKTA_DOMAIN}/api/v1/apps/{bob_app_id}/users?limit=200"
    while url:
        resp = _get(url)
        if resp.status_code != 200:
            raise Exception(f"GET {url} -> {resp.status_code} {resp.text}")

        items = resp.json()
        for item in items:
            user_id = None

            # Preferred: parse from _links.user.href (stable across app types)
            links = item.get("_links", {})
            user_link = None
            if isinstance(links.get("user"), dict):
                user_link = links["user"].get("href")
            elif isinstance(links.get("user"), list) and links["user"]:
                user_link = links["user"][0].get("href")

            if user_link and "/users/" in user_link:
                user_id = user_link.split("/users/")[-1]

            # Fallbacks: embedded user or id that looks like an Okta user id
            if not user_id:
                embedded = item.get("_embedded", {})
                u = embedded.get("user") or {}
                user_id = u.get("id")

            if not user_id:
                maybe = item.get("id")
                if isinstance(maybe, str) and maybe.startswith("00u"):
                    user_id = maybe

            if user_id:
                user_ids.add(user_id)

        # paginate
        next_url = None
        link = resp.headers.get("link") or resp.headers.get("Link")
        if link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    next_url = part[part.find("<") + 1: part.find(">")]
                    break
        url = next_url

    return user_ids


# ----------------------------
# Main
# ----------------------------
# 1) Resolve bob app id
bob_app_id = resolve_bob_app_id()

# 2) Collect users from Okta
users = collect_okta_users()

# 3) Collect all Okta userIds that exist under the bob application
bob_user_ids = collect_bob_user_ids(bob_app_id)

# 4) Transform rows
rows = []
for user in users:
    uid = user.get("id")
    profile = user.get("profile", {}) or {}
    creds = (user.get("credentials", {}) or {}).get("provider", {}) or {}
    provider_type = creds.get("type", "UNKNOWN")
    provider_name = creds.get("name", "UNKNOWN")

    # Your existing provider-based status
    if provider_type == "OKTA":
        provider_status = "Manual (OKTA)"
    elif provider_type in ("FEDERATION", "IMPORT"):
        provider_status = f"Provisioned ({provider_name})"
    else:
        provider_status = provider_name

    # Our bob/manual origin detection
    if uid in bob_user_ids:
        origin = "Imported (bob)"
        # Override provider-status label to reflect origin if you'd like
        okta_configuration_status = "Imported (bob)"
    else:
        origin = "Manual (OKTA)"
        okta_configuration_status = provider_status

    rows.append({
        "User ID": uid,
        "First Name": profile.get("firstName", ""),
        "Last Name": profile.get("lastName", ""),
        "Email": profile.get("email", ""),
        "Origin": origin,  # <-- tells you bob vs manual
        "Okta Configuration Status": okta_configuration_status  # preserves your original intent
    })

# 5) Export to Excel
df = pd.DataFrame(
    rows,
    columns=["User ID", "First Name", "Last Name", "Email", "Origin", "Okta Configuration Status"]
)
output_file = "okta_user_source_report.xlsx"
df.to_excel(output_file, index=False)

print(f"✅ Report generated successfully: {output_file}")
print(f"Total users processed: {len(df)}")
print(f"bob app id used: {bob_app_id}")
