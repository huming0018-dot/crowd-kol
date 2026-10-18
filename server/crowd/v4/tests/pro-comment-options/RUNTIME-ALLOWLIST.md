# Original-profile runtime capability regression

Run `node server/crowd/v4/tests/pro-comment-options/test_runtime_allowlist.mjs` from the repository with four explicit inputs:

- `CROWD_CAPABILITY_EVIDENCE`: local evidence root containing the original `G10-capability-baseline/ACTUAL-HELPER.PRIVATE.json` metadata.
- `CROWD_G07_MIGRATION`: formal `20261018215050_participant_pro_task_comment_options.sql`.
- `CROWD_CAPABILITY_MIGRATION`: formal migration named `participant_original_profile_runtime_allowlist`.
- `CROWD_TEST_TOOLS`: existing tool directory with `@electric-sql/pglite` installed.

Missing inputs fail. The 20 checks use isolated PostgreSQL and preserve old/new runtime eligibility, identity, freshness, quota, entry/worker pins, original function metadata and business rows. No production RPC, platform source or dependency installation runs. Private evidence and Pro code are not bundled.
