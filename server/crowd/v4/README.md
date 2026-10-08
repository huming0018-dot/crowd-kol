# v4 backend source

This isolated authenticated protocol coexists with the legacy public.crowd_* lane.
See ../../../docs/V4_ITERATION.md from the repository root: docs/V4_ITERATION.md.
Historical migrations are imported byte-for-byte from china-travel-food 82cafb7;
IMPORTED_FROM.json records the import. Never replay applied migrations on production.
Apply only new migrations, then verify RPC grants and execute health.sql read-only.

20261008021710_crowd_v4_receipt_recovery was deployed on 2026-10-08.
No legacy ledger/rating/settlement or KOL tables are modified.
Tests use isolated PGlite; real participant identities/records are never synthesized.
The Edge source templates are retained from 4.0.5 and still require the existing
trusted configuration-rendering step before deployment; this iteration changes SQL only.
