# Portfolio privacy architecture

Use pseudonymous borrower, loan, asset and policy identifiers. Mangrove should not require customer
names, national IDs, account numbers or contact data for climate/location analysis.

Preferred modes:
1. customer-side pseudonymisation before upload;
2. customer-controlled database/runtime;
3. hosted secure workspace only after tenant isolation, encryption, access logging and retention rules.

Keep the identity lookup table outside the analytical environment wherever possible.
Support small-cell suppression to reduce re-identification risk.
