---
name: seo-operator
description: Audit configured websites, import GSC and GA4 evidence, prioritize SEO opportunities, validate content, and prepare or safely publish approved updates. Use for evidence-backed SEO operations where production writes must remain gated.
---

# SEO Operator

Work from the repository containing `config.json`. Never enable publishing, add credentials, send outreach, or change a production target without explicit user approval.

1. Run `./run doctor` and report missing connections honestly.
2. Crawl only configured, user-owned sites with a conservative limit.
3. Import GSC/GA4 data before claiming an opportunity; distinguish incomplete query rows from property totals.
4. Run `./run opportunities` and ground recommendations in stored evidence.
5. Validate content offline, then online when source and link access is available.
6. Use `./run stage` before any publish request. Preserve the revision-bound review hash.
7. Keep `publishing_enabled: false` until the user explicitly approves a verified target and rollback path.
8. Run the report after changes and state which evidence remains unavailable.

Read [references/editorial.md](references/editorial.md) before drafting or reviewing publishable content.
