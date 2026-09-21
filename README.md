# Tegami

Tegami is a small, personal outreach and opportunity-tracking toolkit. It
collects early-career opportunities, organizes research contacts, and provides
a deliberately cautious mail-merge workflow for sending personalized messages.

The repository is mostly scripts and local data. The data files are intentionally
kept out of this overview because they contain working contact information and
are useful primarily to the scripts that process them.

## What it does

- **Career watch:** fetches company career pages, finds job-like entries, and
	reports new early-career roles in `state/career_alerts.md`.
- **Industry outreach:** cleans, validates, deduplicates, and batches company
	and hiring contacts for outreach.
- **Research outreach:** keeps faculty contacts grouped by institute type,
	state, city, and institute, with research areas and outreach status.
- **Mailer:** previews personalized messages by default, then sends over SMTP
	only when explicitly asked to do so. It also skips previously sent,
	suppressed, and hard-bounced addresses.

## Project map

```text
tegami/
├── industry/       Career pages and industry outreach data
├── mailer/         SMTP mail-merge utility and message templates
├── research/       Faculty research-outreach data and documentation
├── scripts/        Import, cleanup, batching, validation, and monitoring tools
├── state/          Local snapshots, alerts, and validation state
├── templates/      Outreach message drafts
├── requirements.txt
└── README.md
```

## Setup

Python 3.10+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For JavaScript-rendered career portals, install the optional browser runtime:

```bash
pip install playwright
playwright install chromium
```

## Common workflows

### Monitor career pages

Run from the repository root:

```bash
python scripts/career_watch.py
```

By default, pages are fetched with `requests`. For sites whose listings are
rendered by JavaScript:

```bash
RENDER=1 python scripts/career_watch.py
```

The watcher compares results with its saved snapshot and writes newly detected
roles to the state directory. It is tuned toward fresher, graduate, intern,
trainee, and other entry-level roles.

### Build outreach batches

The industry scripts work against the source data in `industry/`. For example,
to regenerate the standard industry batches:

```bash
python scripts/gen_batches.py
```

Research batching is handled separately:

```bash
python scripts/gen_research_batches.py
```

Review generated output before using it for outreach. Several scripts modify
local data in place.

### Preview and send email

The mailer is a dry run by default:

```bash
python mailer/send.py --file mailer/sample_recipients.csv
```

To send a real campaign, configure `mailer/settings.json`, place the required
template in `mailer/templates/`, and provide SMTP credentials through the local
environment file described in [`mailer/GUIDE.md`](mailer/GUIDE.md). Then pass
the explicit `--send` flag:

```bash
python mailer/send.py --file path/to/recipients.csv --template default --send
```

Useful safeguards include `--limit`, the configured delay between messages, a
daily send cap, duplicate suppression, and bounce suppression. Start with a
small limit and inspect the dry-run output before sending.

## Email and data hygiene

This is a personal tool, not a hosted service. Keep credentials, resumes,
recipient lists, send logs, and other personal data local. Do not commit SMTP
credentials or real recipient data. The mailer includes a synthetic sample and
is designed for relevant, personalized outreach; use it in accordance with
your provider's rules and applicable anti-spam and privacy laws.

## Notes

- `mailer/GUIDE.md` contains the detailed mailer setup and recipient schema.
- `research/README.md` documents the faculty outreach layout and status model.
- Most scripts expect to be run from the repository root unless their help text
	or module documentation says otherwise.

## License

See [`LICENSE`](LICENSE).
