"""
Pulls live status from Jira for the GPT Migration timeline tickets,
rebuilds data.json, and renders index.html from index_template.html.

Requires environment variables:
  JIRA_EMAIL       - the Atlassian account email used to create the API token
  JIRA_API_TOKEN   - an API token from https://id.atlassian.com/manage-profile/security/api-tokens
Optional:
  JIRA_BASE_URL    - defaults to https://czi.atlassian.net
"""
import os
import json
import requests
from datetime import date, timedelta

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://czi.atlassian.net")
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_API_TOKEN = os.environ["JIRA_API_TOKEN"]
EPIC_KEY = "CO-6295"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(REPO_ROOT, "index_template.html")
OUTPUT_PATH = os.path.join(REPO_ROOT, "index.html")
DATA_PATH = os.path.join(REPO_ROOT, "data.json")

CHART_START = date(2026, 9, 26)
CHART_END = date(2026, 12, 20)
TOTAL = (CHART_END - CHART_START).days


def pct(d):
    return round((d - CHART_START).days / TOTAL * 100, 3)


def pct_width(d1, d2):
    return round((d2 - d1).days / TOTAL * 100, 3)


def fetch_jira_statuses(keys):
    """Fetch status + due date for a list of issue keys in one JQL call.

    Uses Jira Cloud's newer /rest/api/3/search/jql endpoint. The older
    /rest/api/3/search endpoint was retired by Atlassian and now returns
    410 Gone, so this must not be reverted to the old URL/pagination style.
    """
    jql = f'"Epic Link" = {EPIC_KEY} OR parent = {EPIC_KEY}'
    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    out = {}
    next_page_token = None
    while True:
        params = {
            "jql": jql,
            "fields": "summary,status,duedate",
            "maxResults": 100,
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        resp = requests.get(
            url,
            params=params,
            auth=(JIRA_EMAIL, JIRA_API_TOKEN),
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        for issue in payload["issues"]:
            key = issue["key"]
            f = issue["fields"]
            due = f.get("duedate")
            category = f["status"]["statusCategory"]["key"]  # 'new' | 'indeterminate' | 'done'
            overdue = False
            if due and category != "done":
                overdue = date.fromisoformat(due) < date.today()
            out[key] = {
                "status": f["status"]["name"],
                "category": category,
                "duedate": due,
                "overdue": overdue,
            }
        if payload.get("isLast", True) or not payload.get("nextPageToken"):
            break
        next_page_token = payload["nextPageToken"]
    return out


def attach_status(item, statuses):
    key = item.get("jira_key")
    if key and key in statuses:
        s = statuses[key]
        item["jira_status"] = s["status"]
        item["jira_category"] = s["category"]
        item["jira_overdue"] = s["overdue"]
    return item


def build_data(statuses):
    data = {
        "chart_start": str(CHART_START), "chart_end": str(CHART_END), "total_days": TOTAL,
        "months": [], "weeks": [], "phases": [], "milestones": [], "testing": [], "comms": [],
        "office_hours": {}, "bands": [],
    }

    for label, d in [("October", date(2026, 10, 1)), ("November", date(2026, 11, 1)), ("December", date(2026, 12, 1))]:
        data["months"].append({"label": label, "left": pct(d)})

    d = date(2026, 9, 28)
    while d <= CHART_END:
        data["weeks"].append({"left": pct(d), "date": d.strftime("%b %-d")})
        d += timedelta(days=7)

    phases = [
        ("Discovery & Analysis", date(2026, 9, 28), date(2026, 10, 9), "phase-discovery",
         "Export inventory, impact analysis, tiering, initial awareness message", "CO-6306"),
        ("Config & Readiness", date(2026, 10, 12), date(2026, 10, 23), "phase-config",
         "Enable plugins/permissions, pilot migration, finalize guides, launch comms", "CO-6308"),
        ("Migration Execution", date(2026, 10, 19), date(2026, 11, 20), "phase-migration",
         "Tier 1 hands-on support, Tier 2 self-serve, orphaned GPTs, custom action reviews", "CO-6309"),
        ("Validation & Close-Out", date(2026, 11, 30), date(2026, 12, 4), "phase-validation",
         "Owners validate plugins, confirm access, final reminders", "CO-6311"),
        ("Hypercare", date(2026, 12, 11), date(2026, 12, 18), "phase-hypercare",
         "Support users who find gaps, resolve remaining issues", "CO-6313"),
    ]
    for name, s, e, cls, desc, key in phases:
        item = {"name": name, "left": pct(s), "width": pct_width(s, e), "cls": cls,
                "start": s.strftime("%b %-d"), "end": e.strftime("%b %-d"), "desc": desc,
                "range": f"{s.strftime('%b %-d')}\u2013{e.strftime('%b %-d')}", "jira_key": key}
        data["phases"].append(attach_status(item, statuses))

    milestones = [
        ("Leadership Decision Gate", date(2026, 10, 9),
         "Review findings, resolve open questions, confirm plugin permissions & retirement date", "CO-6307"),
        ("Creation Cutoff", date(2026, 10, 26),
         "New GPT creation ends; remaining drafts must already be published", "CO-6310"),
        ("Retirement", date(2026, 12, 11), "OpenAI retires custom GPTs workspace-wide", "CO-6312"),
    ]
    for name, d, desc, key in milestones:
        item = {"name": name, "left": pct(d), "date": d.strftime("%b %-d"), "desc": desc, "jira_key": key}
        data["milestones"].append(attach_status(item, statuses))

    testing = [
        ("Phase A \u00b7 Pilot", date(2026, 10, 12), date(2026, 10, 21), "test-pilot",
         "Migrate representative GPTs (knowledge file, connected app, custom action)", "CO-6314"),
        ("Phase B \u00b7 Tier 1 Critical", date(2026, 10, 19), date(2026, 12, 4), "test-tier1",
         "Hands-on migration + validation with primary users, due Dec 4", "CO-6315"),
        ("Phase C \u00b7 General Self-Test", date(2026, 10, 22), date(2026, 12, 4), "test-general",
         "Owner checklist + office hours, due Dec 4", "CO-6316"),
    ]
    for name, s, e, cls, desc, key in testing:
        item = {"name": name, "left": pct(s), "width": pct_width(s, e), "cls": cls,
                "start": s.strftime("%b %-d"), "end": e.strftime("%b %-d"), "desc": desc, "jira_key": key}
        data["testing"].append(attach_status(item, statuses))

    comms = [
        (date(2026, 9, 28), "GPT owners", "What's changing, key dates, publish drafts before Oct 26", "aud-owners", "CO-6296"),
        (date(2026, 10, 12), "Tier 3 owners", "Inactive \u2014 will retire unless you respond by Nov 6", "aud-tier3", "CO-6297"),
        (date(2026, 10, 19), "Tier 1 owners", "Direct outreach to schedule migration support", "aud-tier1", "CO-6298"),
        (date(2026, 10, 22), "GPT owners", "Migration guide + office hours live; cutoff is Monday", "aud-owners", "CO-6299"),
        (date(2026, 10, 30), "GPT owners", "Migrate-or-retire decisions due Nov 6", "aud-owners", "CO-6300"),
        (date(2026, 11, 2), "All users", "How replacement plugins work and how to install them", "aud-all", "CO-6301"),
        (date(2026, 11, 9), "Owners who haven't acted", "Reminder: migrations due Nov 20, support offer", "aud-nudge", "CO-6302"),
        (date(2026, 11, 30), "GPT owners", "Final call: validate and re-share by Dec 4", "aud-owners", "CO-6303"),
        (date(2026, 12, 7), "All users", "Retirement this week, where to get help", "aud-all", "CO-6304"),
        (date(2026, 12, 11), "All users", "GPTs retired, hypercare support details", "aud-all", "CO-6305"),
    ]
    for d, aud, msg, cls, key in comms:
        item = {"left": pct(d), "date": d.strftime("%b %-d"), "audience": aud, "message": msg,
                "cls": cls, "jira_key": key, "jira_url": f"{JIRA_BASE_URL}/browse/{key}"}
        data["comms"].append(attach_status(item, statuses))

    data["office_hours"] = {
        "left": pct(date(2026, 10, 22)), "width": pct_width(date(2026, 10, 22), date(2026, 12, 18)),
        "double_segments": [
            {"left": pct(date(2026, 11, 16)), "width": pct_width(date(2026, 11, 16), date(2026, 11, 20))},
            {"left": pct(date(2026, 11, 30)), "width": pct_width(date(2026, 11, 30), date(2026, 12, 4))},
        ]
    }
    data["bands"].append({
        "label": "Thanksgiving buffer",
        "left": pct(date(2026, 11, 23)),
        "width": pct_width(date(2026, 11, 23), date(2026, 11, 27)),
    })
    data["jira_epic"] = {"key": EPIC_KEY, "url": f"{JIRA_BASE_URL}/browse/{EPIC_KEY}"}
    data["synced_at"] = date.today().isoformat()
    return data


def main():
    statuses = fetch_jira_statuses(None)
    data = build_data(statuses)

    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)

    with open(TEMPLATE_PATH) as f:
        html = f.read()
    html = html.replace("__DATA_JSON__", json.dumps(data))
    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"Synced {len(statuses)} Jira issues. Wrote {OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
