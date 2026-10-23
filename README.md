# UTM Governance Agent

**One campaign, one row in your reports. Catch broken UTMs before launch, and fix the ones already live.**

> Built by Rubia Naseem, GTM Engineer (12+ yrs CRM/RevOps, HubSpot & Salesforce).

---

## The pain point

Every marketing team has a UTM naming doc. Then the paid team types `Google`, the agency sends `linkedin_ad`, lifecycle forgets `utm_medium`, and a month later one campaign is split across three rows and nobody trusts the attribution numbers. Prevention beats audits, so this has a pre-launch check, plus an audit for everything that already slipped through.

- *"...consistency usually breaks when campaign creation is distributed across ad platforms, lifecycle tools, agencies, and one-off launches."* ([r/marketingops: What keeps a UTM naming convention from drifting across teams and agencies?](https://www.reddit.com/r/marketingops/comments/1vz08nx/what_keeps_a_utm_naming_convention_from_drifting/))
- *"Their GA4 source-medium report had email split across 7 rows. Their CFO didn't trust the email attribution numbers at all."* ([r/DigitalMarketing: We retroactively fixed 18 months of mis-tagged email UTMs](https://www.reddit.com/r/DigitalMarketing/comments/1t72w9f/we_retroactively_fixed_18_months_of_mistagged/))

---

## What it does

- **One taxonomy in one place:** approved sources with their typed variants, a closed list of mediums, and a campaign naming rule
- **Catches what splits reports:** capitals, spaces, aliases, channel names used as a medium, missing source or medium, free-text campaign names
- **Flags internal-link tagging**, which overwrites the visitor's real source
- **Shows the damage:** which raw values feed each clean value, and how many contacts sit behind them
- **Fixes it:** a fixed link for every row, a raw-to-clean mapping table and ready-to-paste SQL
- **Pre-launch check:** `--check "<url>"` validates one link and exits with code 1 if it shouldn't go live

---

## Where each step runs

1. **GitHub** holds the code. Clone it or click **Code → Download ZIP**.
2. **Terminal** is where you run it on your UTM sheet or contact export: `python agent.py --input your_file.csv`, or `--check "https://..."` for one link.
3. **Claude is optional.** With an Anthropic key it suggests clean values for rows the rules can't settle and writes the summary. It all stays in the terminal.
4. **You, then your tools.** Check the *review* rows, swap the fixed links into your ads and emails, and use the mapping or SQL to clean historical data.

**The agent never writes to your CRM, ad platforms or analytics.**

---

## Quick start

```bash
git clone https://github.com/rubianaseem/utm-governance-agent.git
cd utm-governance-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python agent.py            # runs on the sample data, no API key needed
```

Check one link before launch:

```bash
python agent.py --check "https://yoursite.com/demo?utm_source=LinkedIn&utm_medium=paid social&utm_campaign=Spring Launch" --platform "LinkedIn Ads"
```

---

## Example output

On `sample_campaign_links.csv` (8 fictional links with made-up contact counts), with no API key:

```text
[FIX] L002  LinkedIn Ads / Sponsored content  (Agency, Brightline Agency, 9 contacts)
    as built : source=LinkedIn | medium=linkedin_ad | campaign=Q4 Demo Push
    clean    : source=linkedin | medium=paid-social | campaign=2026-q4-demo-push   [review]

[BLOCK] L006  Homepage banner / Hero banner  (Website, Web team, 5 contacts)
    clean    : source=- | medium=- | campaign=-   (UTMs removed: internal link)

Split report rows (one real value, several raw values):
  utm_source    google                     <- 'Google', 'google'  (32 contacts)
  utm_campaign  2026-q4-demo-push          <- '2026-q4-demo-push', 'Q4 Demo Push'  (41 contacts)
```

---

## More

- [SETUP.md](SETUP.md): checking links before launch, Claude, your real UTM data, cleaning historical UTMs in HubSpot or your warehouse, extending it, troubleshooting
- [docs/DETAILS.md](docs/DETAILS.md): all the pain-point quotes, full feature list and example output (with the SQL), cost, stack swap table, customising, how this runs today vs production, and what's in the repo
