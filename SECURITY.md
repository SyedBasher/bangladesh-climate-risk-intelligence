# Security and data handling

## Reporting

Please report suspected credential exposure, private-data exposure, or other security-sensitive issues privately to the repository owner rather than opening a public issue containing the sensitive material.

## Data boundary

This public repository must not contain confidential customer information, borrower/policy identifiers tied to real identities, real portfolio data, private asset databases, production credentials, or secret-bearing configuration.

If sensitive data is committed accidentally:

1. stop further distribution;
2. rotate any exposed credential immediately;
3. remove the material from the current tree;
4. rewrite Git history if the sensitive material remains in earlier commits;
5. invalidate or regenerate affected outputs where necessary.

## Secrets

Production secrets should be supplied through environment variables or an appropriate secret manager. Do not commit local credential files such as .cdsapirc, .env, PEM keys, API tokens, database passwords, or cloud-service credentials.

## Customer deployments

For bank, insurer, factory or other customer portfolios, prefer pseudonymous identifiers and minimum necessary data. Where possible, keep identity lookup tables outside the Mangrove analytical environment.
