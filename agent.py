#!/usr/bin/env python3
"""
UTM Governance Agent
--------------------
Audits the UTM tags on your campaign links (or the UTM properties on a HubSpot /
Salesforce contact export), maps every messy variant onto one canonical taxonomy,
shows you where a single campaign has been split into several report rows, and
gives you fixed links, a mapping table, a SQL CASE block and a markdown report.

Runs with no API key (built-in rules). If ANTHROPIC_API_KEY is set, Claude
suggests canonical values for the links the rules can't resolve and writes the
summary. It never writes to your CRM, ad platforms or analytics. It only reads
the CSV you give it and writes files to ./out.

Built by Rubia Naseem, GTM Engineer (12+ yrs CRM/RevOps, HubSpot & Salesforce).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# 1. YOUR TAXONOMY. This is the part to edit for your team.
# ---------------------------------------------------------------------------

# Canonical utm_source values and the variants people actually type.
# Keys are the ONE value you want in reports. Matching is case-insensitive.
SOURCE_ALIASES: dict[str, list[str]] = {
    "google": ["google", "google ads", "google-ads", "googleads", "google_ads", "adwords", "gads"],
    "bing": ["bing", "microsoft ads", "microsoft-ads", "msads"],
    "linkedin": ["linkedin", "li", "lnkd", "linkedin ads", "linkedin-ads", "linkedin_ads"],
    "facebook": ["facebook", "fb", "meta", "fb-ads", "facebook-ads", "meta-ads", "meta ads"],
    "instagram": ["instagram", "ig", "insta"],
    "x": ["x", "twitter", "x.com", "tw"],
    "youtube": ["youtube", "yt"],
    "reddit": ["reddit"],
    "g2": ["g2", "g2crowd", "g2-crowd"],
    "newsletter": ["newsletter", "email-newsletter", "monthly-newsletter"],
    "hubspot": ["hubspot", "hs", "hubspot-email"],
    "customerio": ["customerio", "customer.io", "customer-io", "cio"],
    "partner": ["partner", "partners", "partner-newsletter"],
}

# Sources that are allowed but too generic to be useful on their own.
VAGUE_SOURCES = {"event", "events", "email", "social", "web", "website", "other", "test", "(not set)"}

# Closed list of utm_medium values. My default set; change it to match your
# analytics channel groups (check GA4's default channel group rules for yours).
MEDIUM_ALIASES: dict[str, list[str]] = {
    "cpc": ["cpc", "ppc", "paid-search", "paid_search", "paidsearch", "sem", "search-ads"],
    "paid-social": ["paid-social", "paid_social", "paidsocial", "paid social", "social-paid",
                    "linkedin_ad", "linkedin-ad", "fb_ad", "fb-ad", "meta_ad", "sponsored"],
    "display": ["display", "banner-ad", "programmatic", "retargeting-display"],
    "email": ["email", "e-mail", "mail", "newsletter", "nurture"],
    "social": ["social", "organic-social", "social-organic", "organic_social"],
    "referral": ["referral", "ref"],
    "affiliate": ["affiliate", "affiliates"],
    "partner": ["partner", "co-marketing", "comarketing"],
    "offline": ["offline", "qr", "qr-code", "print", "booth", "event"],
}

# If medium is missing, what a known source almost always means.
SOURCE_DEFAULT_MEDIUM = {
    "newsletter": "email", "hubspot": "email", "customerio": "email",
    "partner": "partner", "g2": "referral",
}

# Campaign naming rule. Default: year-quarter-theme, e.g. 2026-q4-demo-push
DEFAULT_CAMPAIGN_PATTERN = r"^20[0-9]{2}-q[1-4]-[a-z0-9]+(-[a-z0-9]+)*$"

# Export column names the agent recognises (lower-cased, matched loosely).
ALIASES = {
    "id": ["link_id", "id", "record id", "record_id", "contact id", "lead id", "link id"],
    "url": ["url", "link", "tracking url", "tracking_url", "campaign url", "full url", "destination url",
            "first page seen", "landing page"],
    "utm_source": ["utm_source", "utm source", "source (utm)"],
    "utm_medium": ["utm_medium", "utm medium", "medium (utm)"],
    "utm_campaign": ["utm_campaign", "utm campaign", "campaign (utm)"],
    "utm_content": ["utm_content", "utm content"],
    "utm_term": ["utm_term", "utm term"],
    "owner": ["created_by", "created by", "owner", "contact owner", "built by"],
    "team": ["team", "department"],
    "platform": ["platform", "channel", "tool", "sent from"],
    "placement": ["placement", "ad name", "asset", "description"],
    "launch_date": ["launch_date", "launch date", "create date", "created", "start date", "date"],
    "volume": ["contacts_created", "contacts", "sessions", "leads", "clicks", "count"],
}

UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
DEFAULT_MODEL = "claude-sonnet-5-5"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader so there's no extra dependency."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def build_lookup(aliases: dict[str, list[str]]) -> dict[str, str]:
    out = {}
    for canon, variants in aliases.items():
        out[canon.lower()] = canon
        for v in variants:
            out[v.lower()] = canon
    return out


SOURCE_LOOKUP = build_lookup(SOURCE_ALIASES)
MEDIUM_LOOKUP = build_lookup(MEDIUM_ALIASES)


def slugify(value: str) -> str:
    v = unquote_plus(value or "").strip().lower()
    v = re.sub(r"[\s_]+", "-", v)
    v = re.sub(r"[^a-z0-9.\-]", "", v)
    v = re.sub(r"-{2,}", "-", v).strip("-")
    return v


def quarter_of(d: date | None) -> tuple[int, int] | None:
    if not d:
        return None
    return d.year, (d.month - 1) // 3 + 1


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:16], fmt).date()
        except ValueError:
            continue
    return None


def map_columns(header: list[str]) -> dict[str, str]:
    norm = {h.strip().lower(): h for h in header}
    mapping = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in norm:
                mapping[field] = norm[n]
                break
    return mapping


def to_int(value: str) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 2. The rules: audit one link
# ---------------------------------------------------------------------------

def split_url(url: str) -> tuple[str, dict[str, str], list[tuple[str, str]]]:
    """Return (host, utm params with lower-cased keys, other query params)."""
    parts = urlsplit(url.strip())
    utms, other = {}, []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k.lower() in UTM_KEYS:
            utms[k.lower()] = v
        else:
            other.append((k, v))
    return parts.netloc.lower(), utms, other


def fix_campaign(raw: str, launch: date | None, pattern: re.Pattern) -> tuple[str, str]:
    """Return (canonical campaign, how): how is 'ok', 'cleaned' or 'suggested'."""
    if not raw:
        return "", "missing"
    slug = slugify(raw)
    if pattern.match(raw):
        return raw, "ok"
    if pattern.match(slug):
        return slug, "cleaned"
    # Try to rebuild as year-quarter-theme from the name and the launch date.
    tokens = [t for t in slug.split("-") if t]
    year = next((t for t in tokens if re.fullmatch(r"20\d{2}", t)), None)
    qtr = next((t for t in tokens if re.fullmatch(r"q[1-4]", t)), None)
    theme = [t for t in tokens if t not in (year, qtr)]
    yq = quarter_of(launch)
    if not year and yq:
        year = str(yq[0])
    if not qtr and yq:
        qtr = f"q{yq[1]}"
    if year and qtr and theme:
        candidate = f"{year}-{qtr}-{'-'.join(theme)}"
        if pattern.match(candidate):
            return candidate, "suggested"
    return slug, "suggested"


def audit_link(row: dict, cfg: dict) -> dict:
    url = row.get("url", "")
    host, utms, other = ("", {}, [])
    if url:
        host, utms, other = split_url(url)
    # Exports with separate UTM columns (e.g. HubSpot contact properties) win over the URL.
    for k in UTM_KEYS:
        if row.get(k):
            utms[k] = row[k]

    issues: list[tuple[str, str, str]] = []  # (severity, code, message)
    canon: dict[str, str] = {}
    platform = (row.get("platform") or "").lower()

    # --- internal link tagging -------------------------------------------
    internal = bool(host) and host in cfg["internal_domains"] and (
        any(w in platform for w in ("website", "homepage", "banner", "blog", "in-app", "nav"))
    )
    if internal and utms:
        issues.append(("high", "internal_link_tagged",
                       "UTMs on a link inside your own site start a new session and overwrite the visitor's "
                       "real source. Remove them and track the click as an event instead."))

    # --- source ------------------------------------------------------------
    raw_src = utms.get("utm_source", "")
    if internal:
        pass  # the fix is to remove the UTMs, so the values themselves don't matter
    elif not raw_src:
        issues.append(("high", "missing_source", "utm_source is missing, so this traffic lands in '(not set)'."))
    else:
        key = slugify(raw_src)
        if raw_src != raw_src.lower():
            issues.append(("medium", "source_case", f"utm_source '{raw_src}' has capitals. Reports treat it as a different source from '{raw_src.lower()}'."))
        mapped = SOURCE_LOOKUP.get(raw_src.strip().lower()) or SOURCE_LOOKUP.get(key)
        if mapped:
            canon["utm_source"] = mapped
            if mapped != key and mapped != raw_src.lower():
                issues.append(("medium", "source_alias", f"utm_source '{raw_src}' is a variant of '{mapped}'."))
        elif key in VAGUE_SOURCES:
            canon["utm_source"] = key
            issues.append(("low", "vague_source", f"utm_source '{raw_src}' is too generic. Name the platform, list or event instead."))
        else:
            canon["utm_source"] = key
            issues.append(("medium", "unknown_source", f"utm_source '{raw_src}' isn't in your source registry. Add it, or map it to an existing source."))

    # --- medium ------------------------------------------------------------
    raw_med = utms.get("utm_medium", "")
    if internal:
        pass
    elif not raw_med:
        guess = SOURCE_DEFAULT_MEDIUM.get(canon.get("utm_source", ""))
        if not guess and "email" in platform:
            guess = "email"
        msg = "utm_medium is missing, so analytics can't put this traffic in a channel."
        if guess:
            canon["utm_medium"] = guess
            msg += f" Based on the source/platform it should be '{guess}'."
        issues.append(("high", "missing_medium", msg))
    else:
        mapped = MEDIUM_LOOKUP.get(raw_med.strip().lower()) or MEDIUM_LOOKUP.get(slugify(raw_med))
        if raw_med != raw_med.lower():
            issues.append(("medium", "medium_case", f"utm_medium '{raw_med}' has capitals."))
        if mapped:
            canon["utm_medium"] = mapped
            if mapped != raw_med.lower():
                issues.append(("medium", "medium_off_list",
                               f"utm_medium '{raw_med}' isn't on the approved list. It should be '{mapped}'."
                               + (" (A channel name in the medium splits your paid channel.)" if any(s in raw_med.lower() for s in ("linkedin", "fb", "meta")) else "")))
        else:
            canon["utm_medium"] = slugify(raw_med)
            issues.append(("medium", "unknown_medium", f"utm_medium '{raw_med}' isn't on the approved list and has no mapping."))

    # --- campaign ----------------------------------------------------------
    raw_camp = utms.get("utm_campaign", "")
    camp, how = fix_campaign(raw_camp, row.get("_launch"), cfg["campaign_pattern"])
    if internal:
        pass
    elif how == "missing":
        issues.append(("medium", "missing_campaign", "utm_campaign is missing, so this link can't be tied to a campaign."))
    else:
        canon["utm_campaign"] = camp
        if "%20" in url or " " in unquote_plus(raw_camp) or "_" in raw_camp:
            issues.append(("low", "campaign_separators", "utm_campaign uses spaces or underscores. Use hyphens only."))
        if raw_camp != raw_camp.lower():
            issues.append(("medium", "campaign_case", f"utm_campaign '{unquote_plus(raw_camp)}' has capitals."))
        if how == "suggested":
            issues.append(("medium", "campaign_off_pattern",
                           f"utm_campaign '{unquote_plus(raw_camp)}' doesn't follow the naming rule. Suggested: '{camp}' (check it)."))

    for k in ("utm_content", "utm_term"):
        if utms.get(k):
            canon[k] = slugify(utms[k])

    # --- HubSpot email double-tagging check --------------------------------
    if internal:
        canon = {}
    if "hubspot" in platform and "email" in platform and utms:
        issues.append(("low", "check_platform_utms",
                       "HubSpot marketing emails can add their own UTMs to links. Check this link isn't tagged twice "
                       "with different values."))

    # --- build the fixed URL ----------------------------------------------
    fixed_url = ""
    if url:
        parts = urlsplit(url.strip())
        if internal:
            q = urlencode(other)
        else:
            q = urlencode(other + [(k, canon[k]) for k in UTM_KEYS if canon.get(k)])
        fixed_url = urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))

    issues.sort(key=lambda i: SEVERITY_ORDER[i[0]])
    worst = issues[0][0] if issues else None
    status = {"high": "BLOCK", "medium": "FIX", "low": "CHECK", None: "OK"}[worst]
    needs_review = any(c in ("unknown_source", "vague_source", "campaign_off_pattern", "unknown_medium")
                       for _, c, _ in issues)
    return {
        "raw": {k: unquote_plus(utms.get(k, "")) for k in UTM_KEYS},
        "canon": {k: canon.get(k, "") for k in UTM_KEYS},
        "issues": issues,
        "status": status,
        "internal": internal,
        "fixed_url": fixed_url,
        "needs_review": needs_review,
        "fixed_by": "rules",
        "note": "",
    }


# ---------------------------------------------------------------------------
# 3. Optional: Claude for the links the rules can't settle
# ---------------------------------------------------------------------------

def get_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # noqa: WPS433
        return anthropic.Anthropic()
    except Exception as exc:  # pragma: no cover
        print(f"  (anthropic not available: {exc}. Using built-in rules.)")
        return None


def ask_claude(client, model: str, prompt: str, max_tokens: int = 400) -> str:
    resp = client.messages.create(model=model, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": prompt}])
    return "".join(getattr(b, "text", "") for b in resp.content).strip()


def resolve_llm(client, model: str, row: dict, result: dict, cfg: dict) -> dict | None:
    prompt = f"""You are a marketing ops analyst enforcing a UTM taxonomy.
Approved utm_source values: {sorted(SOURCE_ALIASES)} (other values allowed only if clearly a new platform, lowercase-hyphenated).
Approved utm_medium values: {sorted(MEDIUM_ALIASES)}.
Campaign rule (regex): {cfg['campaign_pattern'].pattern}  e.g. 2026-q4-demo-push. Launch date: {row.get('launch_date','unknown')}.
Existing canonical campaigns in this file: {sorted(cfg['known_campaigns'])}. Reuse one if this link clearly belongs to it.

Link: {row.get('url','')}
Platform: {row.get('platform','')}  Placement: {row.get('placement','')}  Team: {row.get('team','')}
Rules suggested: {json.dumps(result['canon'])}
Issues: {[m for _, _, m in result['issues']]}

Return ONLY JSON: {{"utm_source": "...", "utm_medium": "...", "utm_campaign": "...", "note": "one short sentence on what you changed and why"}}"""
    text = ask_claude(client, model, prompt)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    out = {}
    src = slugify(data.get("utm_source", ""))
    med = slugify(data.get("utm_medium", ""))
    camp = slugify(data.get("utm_campaign", ""))
    if src:
        out["utm_source"] = SOURCE_LOOKUP.get(src, src)
    if med in MEDIUM_ALIASES:
        out["utm_medium"] = med
    if camp and cfg["campaign_pattern"].match(camp):
        out["utm_campaign"] = camp
    out["note"] = str(data.get("note", ""))[:240]
    return out


def apply_llm(result: dict, row: dict, suggestion: dict) -> None:
    for k in ("utm_source", "utm_medium", "utm_campaign"):
        if suggestion.get(k):
            result["canon"][k] = suggestion[k]
    result["note"] = suggestion.get("note", "")
    result["fixed_by"] = "claude"
    if row.get("url") and not result["internal"]:
        parts = urlsplit(row["url"].strip())
        other = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in UTM_KEYS]
        q = urlencode(other + [(k, result["canon"][k]) for k in UTM_KEYS if result["canon"].get(k)])
        result["fixed_url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))


# ---------------------------------------------------------------------------
# 4. Roll-ups: fragmentation, mapping table, SQL, summary
# ---------------------------------------------------------------------------

def fragmentation(rows: list[dict], results: list[dict]) -> dict[str, list[dict]]:
    """For each parameter, canonical value -> the raw values feeding it."""
    out: dict[str, list[dict]] = {}
    for k in ("utm_source", "utm_medium", "utm_campaign"):
        groups: dict[str, dict[str, dict]] = defaultdict(dict)
        for row, res in zip(rows, results):
            if res["internal"]:
                continue
            raw, can = res["raw"][k], res["canon"][k]
            if not can:
                continue
            g = groups[can].setdefault(raw or "(missing)", {"links": [], "volume": 0})
            g["links"].append(row.get("id", "?"))
            g["volume"] += row.get("_volume", 0)
        out[k] = [
            {"canonical": can, "variants": variants,
             "volume": sum(v["volume"] for v in variants.values())}
            for can, variants in sorted(groups.items())
        ]
    return out


def mapping_rows(frag: dict) -> list[dict]:
    rows = []
    for param, groups in frag.items():
        for g in groups:
            for raw, info in g["variants"].items():
                if raw != g["canonical"]:
                    rows.append({"parameter": param, "raw_value": raw, "canonical_value": g["canonical"],
                                 "links": " ".join(info["links"]), "volume": info["volume"]})
    return rows


def sql_case(mapping: list[dict]) -> str:
    lines = ["-- Generated by utm-governance-agent. Paste into the query that feeds your dashboards.",
             "-- Keep raw values untouched in the source table; normalise in the reporting layer.", ""]
    for param in ("utm_source", "utm_medium", "utm_campaign"):
        items = [m for m in mapping if m["parameter"] == param and m["raw_value"] != "(missing)"]
        if not items:
            continue
        lines.append("CASE")
        for m in items:
            raw = m["raw_value"].replace("'", "''")
            lines.append(f"  WHEN {param} = '{raw}' THEN '{m['canonical_value']}'")
        lines.append(f"  ELSE {param}\nEND AS {param}_clean,\n")
    return "\n".join(lines).rstrip(",\n") + "\n"


def rules_summary(rows, results, frag) -> str:
    n = len(results)
    counts = defaultdict(int)
    for r in results:
        counts[r["status"]] += 1
    split = [(p, g) for p, gs in frag.items() for g in gs if len(g["variants"]) > 1]
    total_vol = sum(r.get("_volume", 0) for r in rows)
    def need(k):
        return "needs" if counts[k] == 1 else "need"
    noun = "links" if any(r.get("url") for r in rows) else "records"
    parts = [f"{n} {noun} were checked. {counts['OK']} passed, {counts['CHECK']} {need('CHECK')} a quick check, "
             f"{counts['FIX']} {need('FIX')} fixing and {counts['BLOCK']} should not go live as {'it is' if counts['BLOCK'] == 1 else 'they are'}."]
    if split:
        worst = max(split, key=lambda x: (x[1]["volume"], len(x[1]["variants"])))
        p, g = worst
        parts.append(f"{len(split)} canonical values are currently split across several raw values in your reports. "
                     f"The biggest is {p} '{g['canonical']}', which shows up as {len(g['variants'])} different values"
                     + (f" covering {g['volume']} of the {total_vol} contacts in this file." if total_vol else "."))
    internal = sum(1 for r in results if r["internal"])
    if internal:
        parts.append(f"{internal} link{'s are' if internal > 1 else ' is'} UTM-tagging your own site, which overwrites the visitor's real source.")
    return " ".join(parts)


def llm_summary(client, model, base_summary, results) -> str | None:
    issues = defaultdict(int)
    for r in results:
        for _, code, _ in r["issues"]:
            issues[code] += 1
    prompt = (f"Write a 3-sentence plain-English summary for a marketing ops lead about this UTM audit. "
              f"No hype, no invented numbers, only the facts given.\nFacts: {base_summary}\nIssue counts: {dict(issues)}")
    return ask_claude(client, model, prompt, max_tokens=250)


def recommendations(results, frag) -> list[str]:
    codes = defaultdict(int)
    for r in results:
        for _, c, _ in r["issues"]:
            codes[c] += 1
    recs = []
    case = codes["source_case"] + codes["medium_case"] + codes["campaign_case"]
    if case:
        recs.append(f"{case} value{'s' if case != 1 else ''} had capitals. Force lowercase in your link builder, and add a lowercase step to your HubSpot/Salesforce capture workflow as a safety net.")
    if codes["source_alias"] or codes["medium_off_list"]:
        n = codes['source_alias'] + codes['medium_off_list']
        recs.append(f"{n} value{'s were' if n != 1 else ' was a'} typed variant{'s' if n != 1 else ''} of an approved value. Replace free-text source and medium with dropdowns, so nobody types a UTM by hand.")
    if codes["missing_medium"] or codes["missing_source"]:
        n = codes['missing_medium'] + codes['missing_source']
        recs.append(f"{n} link{'s were' if n != 1 else ' was'} missing source or medium. Make both required in the builder and in any agency brief.")
    if codes["campaign_off_pattern"]:
        recs.append(f"{codes['campaign_off_pattern']} campaign name{'s' if codes['campaign_off_pattern'] != 1 else ''} didn't follow the year-quarter-theme rule. Generate the campaign name from fields (year, quarter, theme) instead of free text.")
    if codes["internal_link_tagged"]:
        recs.append("Stop putting UTMs on links inside your own site. Track banner and nav clicks as events.")
    if codes["unknown_source"] or codes["vague_source"]:
        n = codes['unknown_source'] + codes['vague_source']
        recs.append(f"{n} source{'s' if n != 1 else ''} {'weren' if n != 1 else 'wasn'}'t in the registry or {'were' if n != 1 else 'was'} too generic. Have one owner approve new sources, and add them to SOURCE_ALIASES.")
    agencies = {r.get("team", "") for r, res in zip(_ROWS, results) if res["status"] != "OK" and "agency" in (r.get("team", "") + r.get("owner", "")).lower()}
    if agencies:
        recs.append("At least one agency-built link broke the rules. Give agencies the same builder or a pre-approved link list, and run `--check` on links they send before launch.")
    if not recs:
        recs.append("Everything passed. Keep running `--check` on new links before launch.")
    return recs


_ROWS: list[dict] = []


# ---------------------------------------------------------------------------
# 5. Output
# ---------------------------------------------------------------------------

def write_outputs(out_dir: Path, rows, results, frag, mapping, summary, recs, src_name, mode) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}

    p = out_dir / "utm_audit.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "owner", "team", "platform", "status", "issues", "raw_source", "raw_medium", "raw_campaign",
                    "clean_source", "clean_medium", "clean_campaign", "needs_review", "fixed_by", "note", "original_url", "fixed_url"])
        for row, r in zip(rows, results):
            w.writerow([row.get("id"), row.get("owner"), row.get("team"), row.get("platform"), r["status"],
                        "; ".join(c for _, c, _ in r["issues"]),
                        r["raw"]["utm_source"], r["raw"]["utm_medium"], r["raw"]["utm_campaign"],
                        r["canon"]["utm_source"], r["canon"]["utm_medium"], r["canon"]["utm_campaign"],
                        "yes" if r["needs_review"] else "no", r["fixed_by"], r["note"], row.get("url", ""), r["fixed_url"]])
    files["audit"] = p

    p = out_dir / "utm_mapping.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["parameter", "raw_value", "canonical_value", "links", "volume"])
        w.writeheader()
        w.writerows(mapping)
    files["mapping"] = p

    p = out_dir / "normalize_utms.sql"
    p.write_text(sql_case(mapping))
    files["sql"] = p

    if any(row.get("id") and "record" in (row.get("_id_col") or "").lower() for row in rows):
        p = out_dir / "import_clean_utms.csv"
        with p.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Record ID", "UTM Source (clean)", "UTM Medium (clean)", "UTM Campaign (clean)", "Needs review"])
            for row, r in zip(rows, results):
                if r["status"] != "OK":
                    w.writerow([row["id"], r["canon"]["utm_source"], r["canon"]["utm_medium"], r["canon"]["utm_campaign"],
                                "yes" if r["needs_review"] else "no"])
        files["import"] = p

    md = [f"# UTM audit: {src_name}", "",
          f"Run on {date.today().isoformat()} with {mode}. Nothing was written to your CRM, ad platforms or analytics.", "",
          "## Summary", "", summary, "",
          "## Links", "", "| ID | Team | Platform | Status | Issues | Fixed link |", "|---|---|---|---|---|---|"]
    for row, r in zip(rows, results):
        md.append(f"| {row.get('id')} | {row.get('team','')} | {row.get('platform','')} | {r['status']} | "
                  f"{', '.join(c for _, c, _ in r['issues']) or '-'} | `{r['fixed_url'] or '-'}` |")
    md += ["", "## Where one value is split into several report rows", ""]
    any_split = False
    for param, groups in frag.items():
        for g in groups:
            if len(g["variants"]) > 1:
                any_split = True
                vs = ", ".join(f"`{raw}` ({len(i['links'])} link{'s' if len(i['links']) > 1 else ''})" for raw, i in g["variants"].items())
                md.append(f"- **{param} = `{g['canonical']}`** currently appears as {vs}")
    if not any_split:
        md.append("- None in this file.")
    md += ["", "## Fix the process", ""] + [f"- {r}" for r in recs]
    md += ["", "## Files", "", "- `utm_audit.csv`: every link, issues, clean values and fixed URL",
           "- `utm_mapping.csv`: raw value to canonical value, for a warehouse table or a HubSpot/Salesforce normalisation workflow",
           "- `normalize_utms.sql`: CASE statements generated from the mapping"]
    p = out_dir / "utm_report.md"
    p.write_text("\n".join(md) + "\n")
    files["report"] = p
    return files


def print_console(rows, results, frag, summary, recs, src_name, mode, files):
    bar = "=" * 76
    print(bar)
    print(f" UTM GOVERNANCE AGENT  |  {src_name}  |  {len(rows)} links  |  {mode}")
    print(bar)
    for row, r in zip(rows, results):
        vol = f", {row['_volume']} contacts" if row.get("_volume") else ""
        print(f"\n[{r['status']}] {row.get('id')}  {row.get('platform','')} / {row.get('placement','')}  ({row.get('team','')}, {row.get('owner','')}{vol})")
        raw = " | ".join(f"{k.replace('utm_','')}={r['raw'][k] or '-'}" for k in ("utm_source", "utm_medium", "utm_campaign"))
        can = " | ".join(f"{k.replace('utm_','')}={r['canon'][k] or '-'}" for k in ("utm_source", "utm_medium", "utm_campaign"))
        print(f"    as built : {raw}")
        if r["status"] != "OK":
            print(f"    clean    : {can}" + ("   (UTMs removed: internal link)" if r["internal"] else "")
                  + ("   [review]" if r["needs_review"] else ""))
            for sev, _, msg in r["issues"]:
                print(f"    - {sev:<6} {msg}")
            if r["note"]:
                print(f"    claude   : {r['note']}")
            print(f"    fixed    : {r['fixed_url']}")
    print(f"\n{bar}\n SUMMARY\n{bar}\n{summary}\n")
    print("Split report rows (one real value, several raw values):")
    shown = False
    for param, groups in frag.items():
        for g in groups:
            if len(g["variants"]) > 1:
                shown = True
                vs = ", ".join(f"'{raw}'" for raw in g["variants"])
                vol = f"  ({g['volume']} contacts)" if g["volume"] else ""
                print(f"  {param:<13} {g['canonical']:<26} <- {vs}{vol}")
    if not shown:
        print("  none")
    print("\nFix the process:")
    for r in recs:
        print(f"  - {r}")
    print(f"\n{bar}\n FILES (nothing was written to your CRM, ad platforms or analytics)")
    for k, p in files.items():
        print(f"  {k:<8} ./{p}")
    print(bar)


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = map_columns(reader.fieldnames or [])
        if "url" not in cols and not any(k in cols for k in ("utm_source", "utm_medium", "utm_campaign")):
            sys.exit(f"Couldn't find a URL column or UTM columns in {path}. Headers seen: {reader.fieldnames}. "
                     "Add your header names to ALIASES in agent.py.")
        rows = []
        for i, raw in enumerate(reader, 1):
            row = {field: (raw.get(col) or "").strip() for field, col in cols.items()}
            row.setdefault("id", str(i))
            row["id"] = row["id"] or str(i)
            row["_id_col"] = cols.get("id", "")
            row["_launch"] = parse_date(row.get("launch_date", ""))
            row["_volume"] = to_int(row.get("volume", ""))
            rows.append(row)
    return rows


def build_cfg() -> dict:
    domains = os.environ.get("INTERNAL_DOMAINS", "acme.example,www.acme.example")
    return {
        "internal_domains": {d.strip().lower() for d in domains.split(",") if d.strip()},
        "campaign_pattern": re.compile(os.environ.get("CAMPAIGN_PATTERN") or DEFAULT_CAMPAIGN_PATTERN),
        "known_campaigns": set(),
    }


def check_one(url: str, platform: str, cfg: dict) -> int:
    row = {"id": "check", "url": url, "platform": platform, "_launch": date.today(), "_volume": 0}
    r = audit_link(row, cfg)
    print(f"[{r['status']}] {url}")
    for sev, _, msg in r["issues"]:
        print(f"  - {sev:<6} {msg}")
    if r["status"] != "OK":
        print(f"  fixed: {r['fixed_url']}")
    else:
        print("  Looks good. Matches the taxonomy.")
    return 1 if r["status"] == "BLOCK" else 0


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Audit and fix UTM tags against one taxonomy.")
    ap.add_argument("--input", default="sample_campaign_links.csv", help="CSV of campaign links or a contact export with UTM columns")
    ap.add_argument("--output", default="out", help="folder for the output files")
    ap.add_argument("--check", metavar="URL", help="check a single link before launch and exit")
    ap.add_argument("--platform", default="", help="with --check: where the link will be used, e.g. 'LinkedIn Ads' or 'Homepage banner'")
    ap.add_argument("--no-llm", action="store_true", help="use the built-in rules even if ANTHROPIC_API_KEY is set")
    ap.add_argument("--max-llm-links", type=int, default=100, help="cap on links sent to Claude per run")
    args = ap.parse_args()

    cfg = build_cfg()
    if args.check:
        sys.exit(check_one(args.check, args.platform, cfg))

    path = Path(args.input)
    if not path.exists():
        sys.exit(f"Input file not found: {path}")
    rows = read_rows(path)
    _ROWS.extend(rows)
    results = [audit_link(r, cfg) for r in rows]
    cfg["known_campaigns"] = {r["canon"]["utm_campaign"] for r in results
                              if r["canon"]["utm_campaign"] and not r["needs_review"]}

    client = None if args.no_llm else get_client()
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    mode = f"Claude ({model})" if client else "built-in rules (no API key)"
    if client:
        failures, sent = 0, 0
        for row, res in zip(rows, results):
            if not res["needs_review"] or res["internal"] or sent >= args.max_llm_links or failures >= 2:
                continue
            sent += 1
            try:
                s = resolve_llm(client, model, row, res, cfg)
                if s:
                    apply_llm(res, row, s)
                failures = 0
            except Exception as exc:  # fall back to rules on any API error
                failures += 1
                print(f"  (Claude call failed for {row.get('id')}: {type(exc).__name__}. Using rules.)")
        if failures >= 2:
            mode += ", fell back to rules after errors"

    frag = fragmentation(rows, results)
    mapping = mapping_rows(frag)
    summary = rules_summary(rows, results, frag)
    if client:
        try:
            summary = llm_summary(client, model, summary, results) or summary
        except Exception:
            pass
    recs = recommendations(results, frag)
    files = write_outputs(Path(args.output), rows, results, frag, mapping, summary, recs, path.name, mode)
    print_console(rows, results, frag, summary, recs, path.name, mode, files)


if __name__ == "__main__":
    main()
