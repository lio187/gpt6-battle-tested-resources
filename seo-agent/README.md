# SEO Operator

A generic, local-first SEO workflow extracted from the working-session build. It combines technical crawling, GSC/GA4 imports, opportunity scoring, evidence-gated content review, draft packaging, publishing adapters and an optional local CRM event ledger.

Production writes are disabled in the example configuration. Nothing sends outreach automatically.

## Quick start

```bash
cp config.example.json config.json
python3 -m venv .venv
.venv/bin/pip install -e .
./run doctor
./run crawl --site primary --limit 25
```

Replace every `example.com` value before crawling. For Google read-only access, create a Desktop OAuth client and run:

```bash
.venv/bin/python scripts/google_oauth.py /path/to/oauth-client-config.json
export GOOGLE_OAUTH_TOKEN_FILE="$HOME/.config/seo-operator/google-token.json"
./run sync --days 28
./run opportunities
./run report
```

## Safety model

- `publishing_enabled` starts as `false`.
- Each site publisher starts as `disabled`.
- Content needs a revision-bound review record before staging.
- Static deployment requires both verified deploy and rollback commands.
- Payload publishing validates the configured account identity.
- CRM intake binds to loopback, requires a bearer key and stores an append-only event ledger.
- Credentials live outside this repository.

The optional CRM adapter reads `SEO_OPERATOR_INTAKE_KEY`, `SEO_OPERATOR_CRM_API_KEY` and `SEO_OPERATOR_CRM_OWNER_ID` from the environment. Copy `crm-config.example.json` to `crm-config.json` before running `seo-crm`.

See [`skills/seo-operator/SKILL.md`](skills/seo-operator/SKILL.md) for the agent workflow and [`examples/article.json`](examples/article.json) for the content contract.
