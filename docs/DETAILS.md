# Details: UTM Governance Agent

Everything that used to sit in the main README, kept here so the README stays short. Back to the [README](../README.md).

## Background

Every marketing team has a UTM naming doc. Then the paid team types `Google`, the agency sends `linkedin_ad` and `Q4 Demo Push`, lifecycle forgets `utm_medium` on a Customer.io send, and someone tags the homepage banner. A month later the HubSpot or GA4 report shows one campaign split across three rows, email traffic sitting in "(not set)", and nobody trusts the attribution numbers.

This agent reads your campaign links (or the UTM properties on a HubSpot or Salesforce contact export), checks every value against one taxonomy, and gives you fixed links, a raw-to-clean mapping table, ready-to-paste SQL, and a short report on where your reports are being split and why. It also has a `--check` mode, so a link can be validated before it goes live instead of being audited after.

## Where each step runs (full version)

If you can create a repo but aren't sure where you actually *run* this, here's the whole flow in order:

1. **GitHub** is where the code lives. Copy it to your laptop with `git clone https://github.com/rubianaseem/utm-governance-agent.git`, or click **Code → Download ZIP** and unzip it.
2. **Terminal** (Mac Terminal, or the terminal inside Cursor) is where you run the script on your CSV: your UTM tracking sheet, a link export, or a HubSpot contact export with UTM properties. Set it up once, then run `python agent.py --input your_file.csv` (see [Quick start](../README.md#-quick-start)). To check one link before launch, run `python agent.py --check "https://..."`.
3. **Claude is optional.** With no API key the agent uses its built-in rules. If you add an Anthropic API key to `.env`, it asks Claude to suggest clean values for the links the rules can't settle (an unknown source, a free-text campaign name) and to write the summary. It still runs in the terminal. You don't open the Claude app or paste anything into a chat.
4. **You, then your tools.** Open `out/utm_report.md` and `out/utm_audit.csv`, check the rows marked *review*, then swap the fixed links into your ads, emails and QR codes yourself. Use `out/utm_mapping.csv` or `out/normalize_utms.sql` to clean historical data in your reporting layer, and, if you ran it on a HubSpot contact export, import `out/import_clean_utms.csv` into clean UTM properties (steps in [SETUP.md](../SETUP.md#6-optional-clean-historical-utms-in-hubspot-or-your-warehouse)).

**The agent never writes to your CRM, ad platforms or analytics.** It only reads the CSV you give it and creates files on your computer.

## Full feature list

- **One taxonomy, in one place:** canonical sources with their typed variants (`fb`, `meta`, `Facebook` → `facebook`), a closed list of mediums, and a campaign naming rule (default `year-quarter-theme`, e.g. `2026-q4-demo-push`)
- **Catches the mistakes that split reports:** capitals, spaces and underscores, aliases, channel names used as a medium (`linkedin_ad`), missing `utm_source` or `utm_medium`, free-text campaign names, vague sources like `event`
- **Flags internal-link tagging:** UTMs on your own homepage banners or nav overwrite the visitor's real source, so the fix is to remove them
- **HubSpot email check:** reminds you that HubSpot marketing emails can add their own UTMs, so a manually tagged link may be tagged twice
- **Shows the damage:** for each clean value, which raw values are feeding it today and how many contacts (or sessions) sit behind them
- **Fixed link for every row:** same page, same non-UTM parameters, clean UTMs
- **Pre-launch check:** `--check "<url>"` validates one link in a second, and exits with code 1 if it should not go live, so you can drop it into a script or an n8n step
- **Reads real exports:** link sheets with a URL column, or HubSpot/Salesforce exports with `UTM Source`, `UTM Medium`, `UTM Campaign` columns and a `Record ID`
- **Outputs you can use:** `utm_audit.csv`, `utm_mapping.csv`, `normalize_utms.sql`, `utm_report.md`, plus `import_clean_utms.csv` for HubSpot contact exports
- **Works with no API key.** Claude is an upgrade, not a requirement, and any API error falls back to the rules

## The pain point: all quotes and sources

This one came straight from [r/marketingops](https://www.reddit.com/r/marketingops/comments/1vz08nx/what_keeps_a_utm_naming_convention_from_drifting/). The naming doc exists. It just isn't what decides the values that end up in the CRM.

- *"...consistency usually breaks when campaign creation is distributed across ad platforms, lifecycle tools, agencies, and one-off launches."* ([r/marketingops: What keeps a UTM naming convention from drifting across teams and agencies?](https://www.reddit.com/r/marketingops/comments/1vz08nx/what_keeps_a_utm_naming_convention_from_drifting/))
- *"Make sure no one is actually typing UTM's."* and *"You don't want to do audits if you can avoid it, trust me!"* (a reply in the same thread)
- *"Their GA4 source-medium report had email split across 7 rows. Their CFO didn't trust the email attribution numbers at all."* ([r/DigitalMarketing: We retroactively fixed 18 months of mis-tagged email UTMs](https://www.reddit.com/r/DigitalMarketing/comments/1t72w9f/we_retroactively_fixed_18_months_of_mistagged/))
- *"Mixed-case source values. "Facebook" and "facebook" coexist within 30 days of any team without enforcement."* ([r/analytics: UTM naming patterns that hold up after 12+ months](https://www.reddit.com/r/analytics/comments/1t602vq/utm_naming_patterns_that_hold_up_after_12_months/), from a poster who disclosed they work on a UTM tool)
- *"HubSpot will associate assets to the campaign as long as utm_campaign exactly matches "ntc" case sensitive."* and *"emails sent from HubSpot auto-append UTMs anyway, so double check naming to avoid duplicates."* ([r/hubspot: A question about HubSpot campaigns and UTM tracking](https://www.reddit.com/r/hubspot/comments/1qvp9ow/a_question_about_hubspot_campaigns_and_utm/))

I agree with that reply: prevention beats audits. That's why this has a `--check` mode for links before they go out. But most teams already have months of messy values live, plus agencies and tools they don't fully control, so the audit and the mapping table are the safety net for everything that already slipped through.

## Quick start (full)

```bash
git clone https://github.com/rubianaseem/utm-governance-agent.git
cd utm-governance-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python agent.py            # runs on the sample data, no API key needed
```

Use your own file:

```bash
python agent.py --input ~/Downloads/utm_tracking_sheet.csv --output out/q4
```

Check one link before launch:

```bash
python agent.py --check "https://yoursite.com/demo?utm_source=LinkedIn&utm_medium=paid social&utm_campaign=Spring Launch" --platform "LinkedIn Ads"
```

Optional: `cp .env.example .env` and add your `ANTHROPIC_API_KEY`. Set `INTERNAL_DOMAINS` to your own domains so internal-link tagging is caught. Use `--no-llm` to force the rules even when a key is set. Full walkthrough in [SETUP.md](../SETUP.md).

## Full example output (sample data, no API key)

This is the real output of `python agent.py` on `sample_campaign_links.csv` (8 fictional links for a fictional company, `acme.example`, with made-up contact counts), run on 19 Oct 2026. Trimmed to four of the eight links; the full run prints all of them.

```text
============================================================================
 UTM GOVERNANCE AGENT  |  sample_campaign_links.csv  |  8 links  |  built-in rules (no API key)
============================================================================

[FIX] L002  LinkedIn Ads / Sponsored content  (Agency, Brightline Agency, 9 contacts)
    as built : source=LinkedIn | medium=linkedin_ad | campaign=Q4 Demo Push
    clean    : source=linkedin | medium=paid-social | campaign=2026-q4-demo-push   [review]
    - medium utm_source 'LinkedIn' has capitals. Reports treat it as a different source from 'linkedin'.
    - medium utm_medium 'linkedin_ad' isn't on the approved list. It should be 'paid-social'. (A channel name in the medium splits your paid channel.)
    - medium utm_campaign 'Q4 Demo Push' has capitals.
    - medium utm_campaign 'Q4 Demo Push' doesn't follow the naming rule. Suggested: '2026-q4-demo-push' (check it).
    - low    utm_campaign uses spaces or underscores. Use hyphens only.
    fixed    : https://acme.example/demo?utm_source=linkedin&utm_medium=paid-social&utm_campaign=2026-q4-demo-push

[BLOCK] L004  Customer.io / Webinar invite #2  (Lifecycle, Nadia Brooks, 11 contacts)
    as built : source=customerio | medium=- | campaign=2026-q4-webinar-ai-ops
    clean    : source=customerio | medium=email | campaign=2026-q4-webinar-ai-ops
    - high   utm_medium is missing, so analytics can't put this traffic in a channel. Based on the source/platform it should be 'email'.
    fixed    : https://acme.example/webinar?utm_source=customerio&utm_medium=email&utm_campaign=2026-q4-webinar-ai-ops

[BLOCK] L006  Homepage banner / Hero banner  (Website, Web team, 5 contacts)
    as built : source=homepage | medium=banner | campaign=2026-q4-webinar-ai-ops
    clean    : source=- | medium=- | campaign=-   (UTMs removed: internal link)
    - high   UTMs on a link inside your own site start a new session and overwrite the visitor's real source. Remove them and track the click as an event instead.
    fixed    : https://acme.example/webinar

[OK] L008  Google Ads / Search - generic  (Paid, Sam Okafor, 18 contacts)
    as built : source=google | medium=cpc | campaign=2026-q4-demo-push

============================================================================
 SUMMARY
============================================================================
8 links were checked. 1 passed, 0 need a quick check, 5 need fixing and 2 should not go live as they are. 5 canonical values are currently split across several raw values in your reports. The biggest is utm_campaign '2026-q4-demo-push', which shows up as 2 different values covering 41 of the 74 contacts in this file. 1 link is UTM-tagging your own site, which overwrites the visitor's real source.

Split report rows (one real value, several raw values):
  utm_source    google                     <- 'Google', 'google'  (32 contacts)
  utm_medium    cpc                        <- 'CPC', 'cpc'  (32 contacts)
  utm_medium    email                      <- 'Email', '(missing)'  (17 contacts)
  utm_medium    paid-social                <- 'linkedin_ad', 'paid_social'  (13 contacts)
  utm_campaign  2026-q4-demo-push          <- '2026-q4-demo-push', 'Q4 Demo Push'  (41 contacts)

Fix the process:
  - 6 values had capitals. Force lowercase in your link builder, and add a lowercase step to your HubSpot/Salesforce capture workflow as a safety net.
  - 4 values were typed variants of an approved value. Replace free-text source and medium with dropdowns, so nobody types a UTM by hand.
  - 1 link was missing source or medium. Make both required in the builder and in any agency brief.
  - 3 campaign names didn't follow the year-quarter-theme rule. Generate the campaign name from fields (year, quarter, theme) instead of free text.
  - Stop putting UTMs on links inside your own site. Track banner and nav clicks as events.
  - 1 source wasn't in the registry or was too generic. Have one owner approve new sources, and add them to SOURCE_ALIASES.
  - At least one agency-built link broke the rules. Give agencies the same builder or a pre-approved link list, and run `--check` on links they send before launch.

============================================================================
 FILES (nothing was written to your CRM, ad platforms or analytics)
  audit    ./out/utm_audit.csv
  mapping  ./out/utm_mapping.csv
  sql      ./out/normalize_utms.sql
  report   ./out/utm_report.md
============================================================================
```

And this is the first block of `out/normalize_utms.sql` from the same run:

```sql
CASE
  WHEN utm_source = 'fb' THEN 'facebook'
  WHEN utm_source = 'Google' THEN 'google'
  WHEN utm_source = 'LinkedIn' THEN 'linkedin'
  ELSE utm_source
END AS utm_source_clean,
```

## 💷 Cost (estimate)

- **Without an API key:** free. It's plain Python running on your laptop.
- **With `ANTHROPIC_API_KEY`:** Claude is only called for rows the rules mark *review* (unknown or vague source, campaign name that doesn't fit the rule), plus one call for the summary. Clean rows and rows the rules can fix never go to Claude. My rough estimate, based on [Anthropic's list pricing](https://platform.claude.com/docs/en/about-claude/pricing) for Claude Sonnet 5.5 ($2 per million input tokens, $10 per million output tokens) and about 600 input and 100 output tokens per call, is a fraction of a US cent per call: around a cent for the sample, and well under a dollar for a few hundred review rows. I haven't measured this on a large real export, so treat it as a ballpark. `--max-llm-links` (default 100) caps how many rows go to Claude per run.

## 🔁 Stack swap table

| Layer | In this repo | Swap for |
|---|---|---|
| Link source | `sample_campaign_links.csv` | Your UTM tracking sheet (Google Sheets / Excel export), Bitly or Dub link export, ad platform URL exports |
| Contact source | HubSpot/Salesforce export with UTM columns | HubSpot API (contact properties), Salesforce report or SOQL, Marketo / Pardot field exports |
| Session source | Not included | GA4 source/medium/campaign export, GA4 → BigQuery tables |
| Taxonomy | `SOURCE_ALIASES`, `MEDIUM_ALIASES`, `CAMPAIGN_PATTERN` | Your naming sheet, a shared JSON/YAML file owned by marketing ops |
| Suggestions | Rules → Claude | OpenAI, Grok, Gemini or a local model; swap the one function `resolve_llm` |
| Output | Local CSV, SQL, Markdown | A HubSpot normalisation workflow, a dbt model or BigQuery view, a Slack alert to the link owner |
| Orchestration | You run it, or `--check` per link | n8n / Zapier / Make on new rows in the tracking sheet, or a weekly audit |

## 🛠 Customise it for your stack

Everything you'll want to tune is at the top of `agent.py`:

- **`SOURCE_ALIASES`:** your approved sources and the variants your team actually types. New platform? Add it here, once.
- **`MEDIUM_ALIASES`:** your closed list of mediums. My defaults are `cpc`, `paid-social`, `display`, `email`, `social`, `referral`, `affiliate`, `partner`, `offline`. Check them against the channel groups your analytics tool uses.
- **`SOURCE_DEFAULT_MEDIUM`:** what a missing medium should be for a known source (e.g. `customerio` → `email`)
- **`VAGUE_SOURCES`:** values you allow but want flagged, like `event` or `social`
- **`CAMPAIGN_PATTERN`** (in `.env`): your campaign naming rule as a regex. The default is `year-quarter-theme`.
- **`INTERNAL_DOMAINS`** (in `.env`): your own domains, so UTMs on internal banners are caught
- **`ALIASES`:** your exact export headers, e.g. `UTM Campaign (first touch)` or a custom Salesforce field

## 🧭 How this runs today (and what production would add)

I want to be straight about what this is: a working **audit and check tool you run on a file**, not a link-governance platform.

**Today:**
- **No auto-trigger.** You export the links or contacts and run it by hand, or run `--check` on a link before launch.
- **Prints to the console** and writes local files. **It never writes to your CRM, ad platforms or analytics.** Swapping in fixed links and importing clean values are manual.
- **Rules first.** Matching is based on the alias lists you maintain. A value it hasn't seen is flagged for review, not guessed. Suggested campaign names (and Claude's suggestions) are marked *review* because they can be wrong.
- **Internal-link detection is simple.** It flags a link as internal when the destination is one of your `INTERNAL_DOMAINS` and the platform looks like your own site (banner, homepage, nav, blog). It doesn't crawl your site.
- **It doesn't rewrite history.** It gives you the mapping and SQL to clean historical data in your reporting layer. Raw values stay as they are.
- **No memory.** It doesn't learn from the corrections you make in the audit file.

**What production would add:**
- A link builder or intake form (Google Sheet, HubSpot form, Slack shortcut) that calls `--check` before a link can be saved
- A scheduled run (n8n, my default) on new rows in the tracking sheet and on new contacts with UTM values
- A Slack message to the person or agency who built a broken link, with the fixed version
- A HubSpot workflow or Salesforce flow that writes clean UTM values to separate properties, keeping the raw ones
- A warehouse model (dbt or a BigQuery view) built from `utm_mapping.csv`, owned by marketing ops
- One owner and an approval step for new sources and mediums, with a change log

## 📁 What's in the repo

```
utm-governance-agent/
├── agent.py                    # the agent
├── sample_campaign_links.csv   # 8 fictional campaign links
├── requirements.txt            # anthropic (optional, only used with a key)
├── .env.example                # API key, model, internal domains, campaign rule
├── docs/DETAILS.md             # this file: everything moved out of the README
├── SETUP.md                    # setup, real exports, cleaning history, extending, troubleshooting
├── LICENSE                     # MIT
└── README.md
```

---

If you own the UTM sheet at your company, I'd like to know which value breaks most often for you: source, medium or campaign name.
