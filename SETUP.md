# Setup guide

This walks through everything in order: install, a first run on the sample data, checking a single link, adding Claude, running it on your real UTM data from a tracking sheet, HubSpot or Salesforce, and (optionally) cleaning historical values.

You need **Python 3.9 or newer**. Check with `python3 --version` in Terminal.

---

## 1. Get the code and create a virtual environment

Run these in **Terminal** (Mac Terminal, or the terminal panel in Cursor):

```bash
git clone https://github.com/rubianaseem/utm-governance-agent.git
cd utm-governance-agent

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The virtual environment (`.venv`) keeps this project's packages separate from everything else on your laptop. Run `source .venv/bin/activate` again whenever you open a new terminal.

## 2. Run it on the sample data

```bash
python agent.py
```

No API key needed. You'll see one block per link in the terminal (status, what was built, the clean values, each issue and the fixed link), then a summary, and these files in `out/`:

| File | What it's for |
|---|---|
| `out/utm_audit.csv` | One row per link: status, issue codes, raw values, clean values, whether it needs review, original and fixed URL |
| `out/utm_mapping.csv` | Every raw value that should become a different clean value, with the links and contact counts behind it |
| `out/normalize_utms.sql` | `CASE` statements built from the mapping, to paste into the query behind your dashboards |
| `out/utm_report.md` | The readout: summary, link table, split report rows, process fixes |
| `out/import_clean_utms.csv` | Only when the input is a contact export with a `Record ID`: clean values to import into HubSpot |

Statuses: **OK** (matches the taxonomy), **CHECK** (only low-severity notes), **FIX** (wrong values that will split reports), **BLOCK** (missing source or medium, or UTMs on an internal link; don't launch it like this). Rows marked **review** have a suggested value a person should confirm, such as a rebuilt campaign name.

## 3. Check a single link before launch

```bash
python agent.py --check "https://yoursite.com/demo?utm_source=LinkedIn&utm_medium=paid social&utm_campaign=Spring Launch" --platform "LinkedIn Ads"
```

It prints the issues and the fixed link. The exit code is `1` when the status is BLOCK and `0` otherwise, so you can call it from a script, a pre-launch checklist or an n8n **Execute Command** node. `--platform` is optional; it helps spot internal links (e.g. `--platform "Homepage banner"`) and HubSpot email links. Campaign names are rebuilt with today's date when the quarter or year is missing.

## 4. Optional: add Claude

```bash
cp .env.example .env
```

Open `.env` and paste your key after `ANTHROPIC_API_KEY=` (get one at https://console.anthropic.com). The default model is `claude-sonnet-5-5`; change `ANTHROPIC_MODEL` if you want another one.

Run `python agent.py` again. The header now says `Claude (claude-sonnet-5-5)`. Claude only sees rows marked *review*: it suggests a source, medium and campaign name, and the agent only accepts a medium from your approved list and a campaign name that matches your rule. Its note shows under `claude :` in the terminal and in the `note` column, and `fixed_by` says `claude`. If a call fails (bad key, no credit, network), that row keeps the rules' answer. After two failures in a row the rest of the run uses the rules too. Use `--no-llm` to skip Claude even when a key is set.

`.env` is in `.gitignore`, so your key is never committed.

Other settings in `.env`:

- `INTERNAL_DOMAINS`: your own domains, comma-separated. Set this, or internal-link tagging won't be caught.
- `CAMPAIGN_PATTERN`: your campaign naming rule as a regular expression. The default accepts `2026-q4-demo-push`.

## 5. Run it on your real UTM data

The agent needs **either** a URL column **or** separate UTM columns. Everything else (owner, team, platform, launch date, a contact or session count) makes the report more useful. Column names are matched automatically (see `ALIASES` in `agent.py`).

| Agent field | UTM tracking sheet | HubSpot contact export | Salesforce report |
|---|---|---|---|
| `id` | Link ID, or row number | Record ID | Lead ID / Contact ID |
| `url` | Full tracking URL | (not needed) | (not needed) |
| `utm_source`, `utm_medium`, `utm_campaign` | (read from the URL) | Your UTM contact properties, e.g. `UTM Source` | Your custom UTM fields |
| `owner`, `team` | Created by, Team | Contact owner | Owner |
| `platform`, `placement` | Platform, Ad / asset name | (optional) | (optional) |
| `launch_date` | Launch date | Create Date | Created Date |
| `volume` | Contacts, leads or sessions | (leave out; each row is one contact) | (leave out) |

### Your UTM tracking sheet (Google Sheets or Excel)

1. In Google Sheets: **File → Download → Comma-separated values (.csv)**. In Excel: **File → Save As → CSV UTF-8**.
2. Run: `python agent.py --input ~/Downloads/<your-sheet>.csv --output out/sheet`

### HubSpot

HubSpot doesn't store raw UTM values on contacts by default (Original Source and its drill-downs are system properties). Most teams create their own UTM contact properties and fill them with hidden form fields. If you have those:

1. Go to **CRM → Contacts** and switch to the table view.
2. Filter: your `UTM Campaign` property **is known**, and **Create date** in the period you care about.
3. Click **Edit columns** and add Record ID, your UTM properties and Create Date.
4. Click **Export**, choose **CSV**, and include only the columns in the view. HubSpot emails you a download link when the file is ready.
5. Run: `python agent.py --input ~/Downloads/<your-export>.csv --output out/hubspot`

If you don't have UTM properties yet, that's the first fix: create them and map them as hidden fields on your forms, so the values land on the contact.

### Salesforce

1. Go to **Reports → New Report → Leads** (or Contacts, or Campaign Members if that's where your UTM fields live).
2. Add the ID, your UTM fields and Created Date as columns, and filter to your period.
3. Click the arrow next to **Edit → Export → Details Only**, format **Comma Delimited .csv**.
4. Run: `python agent.py --input ~/Downloads/<your-report>.csv --output out/salesforce`

If your column names differ (custom field names, other languages), add them to `ALIASES` at the top of `agent.py`.

## 6. Optional: clean historical UTMs in HubSpot or your warehouse

The agent never does this for you, and it's worth keeping the raw values untouched. Write clean values to separate fields instead.

### Fix the live links first

Use the `fixed_url` column in `out/utm_audit.csv` to update ads, emails, QR codes and partner links that are still running. Confirm the rows marked *review* before you swap them in.

### HubSpot (contact export input only)

1. **Settings → Properties → Contact properties → Create property:** `UTM Source (clean)`, `UTM Medium (clean)`, `UTM Campaign (clean)` (single-line text, or dropdowns that match your taxonomy).
2. Open `out/import_clean_utms.csv` and check or delete the rows where `Needs review` is `yes`.
3. **CRM → Contacts → Import → Start an import → File from computer → One file → One object → Contacts.**
4. Choose to update existing records, matched on **Record ID**, so no new contacts get created.
5. Map the three clean columns to the new properties, choose **Don't import column** for `Needs review`, and finish the import.
6. Build your campaign reports on the clean properties.

To keep new contacts clean, add a contact workflow that copies the raw UTM properties to the clean ones and uses `utm_mapping.csv` as your lookup (if/then branches, or a custom code action if your HubSpot tier has one).

### Warehouse or BI tool

Paste the blocks in `out/normalize_utms.sql` into the query or dbt model that feeds your dashboards, or load `out/utm_mapping.csv` as a lookup table and join on `parameter` + `raw_value`. The SQL only covers typed variants. Missing values (shown as `(missing)` in the mapping) have to be fixed at the link.

## 7. Extend it with an AI coding tool

The code is one file with clear sections, so it's easy to extend with an AI coding assistant. Open the folder in your tool and try prompts like these:

- **Cursor:** open the folder, press Cmd+L and ask: *"Add support for a GA4 traffic acquisition export where source and medium come in one 'Session source / medium' column, and use the Sessions column as volume."*
- **Claude Code:** run `claude` in the project folder and ask: *"Move SOURCE_ALIASES, MEDIUM_ALIASES and the campaign rule into a taxonomy.yaml file so marketing ops can edit it without touching Python."*
- **Codex CLI:** run `codex` in the folder and ask: *"When a link is BLOCK or FIX, post the fixed URL to a Slack webhook from `.env`, mentioning the owner column."*
- **Grok:** paste `agent.py` and ask it to add a `utm_content` rule for your A/B test naming (e.g. `variant-a`, `variant-b`).

Ask the tool to run `python agent.py` afterwards and check that the sample still gives 1 OK, 5 FIX and 2 BLOCK.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `Couldn't find a URL column or UTM columns` | Your headers have names the agent doesn't know. Add them to `ALIASES["url"]` or `ALIASES["utm_source"]` etc., or rename the column to `url` / `UTM Source`. |
| A homepage banner isn't flagged as internal | Set `INTERNAL_DOMAINS` in `.env` to your domains, and make sure the platform column says something like "Homepage banner", "Website" or "Blog". |
| A real source is flagged `unknown_source` | It isn't in `SOURCE_ALIASES` yet. Add it (and its variants) once, and every future run will accept it. |
| Campaign names you're happy with are flagged | Your naming rule is different from the default. Change `CAMPAIGN_PATTERN` in `.env`. |
| Suggested campaign names have the wrong quarter | The agent uses the launch date column. If there's none, `--check` uses today's date. Add a launch or create date column. |
| `Claude call failed (AuthenticationError)` | The key in `.env` is wrong or has no credit. The run still finishes using the rules. |
| `Claude call failed (NotFoundError)` | The model name in `ANTHROPIC_MODEL` isn't available on your account. Pick one from Anthropic's models page. |
| `ModuleNotFoundError: anthropic` | Activate the venv (`source .venv/bin/activate`) and run `pip install -r requirements.txt`. Without a key the agent doesn't need it at all. |
| Weird characters in values | Export as UTF-8 CSV. The agent already handles the Excel byte-order mark and URL-encoded spaces. |
