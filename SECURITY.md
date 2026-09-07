# Security policy

Do not commit credentials, OAuth files, customer data, analytics exports or runtime databases. Use environment variables or files outside the repository.

The SEO agent rejects private-network crawl targets, limits response sizes, keeps production writes disabled by default and binds its CRM intake server to `127.0.0.1`. Those controls reduce risk; they are not a substitute for reviewing your configuration, dependencies and deployment target.

Report a vulnerability through a private GitHub security advisory for this repository. Do not include live secrets or personal data in an issue.
