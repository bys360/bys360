# BYS360 Release Verification

Audience: an operator who has just received a FULL release ZIP
(`BYS360_FULL_LIVE_<SHA>.zip`) and needs to independently confirm it is legitimate and
complete **before** using it for candidate preparation.

## 1. SHA256 check against its own manifest

Every release built by `scripts/release/build_bys360_safe_release.py` produces three
artifacts together:

- `BYS360_FULL_LIVE_<SHA>.zip` — the package itself.
- `BYS360_FULL_LIVE_<SHA>.manifest.json` — a sidecar manifest (schema_version `2` as of
  this writing) recording `source_sha`, `included_count`, the full sorted `files` list,
  `excluded_count`/`excluded_sample`, and the name of the accompanying sha256sums file.
- `BYS360_FULL_LIVE_<SHA>.sha256sums.txt` — one `<sha256>  <path>` line per file in the
  package.

To verify:

```
python scripts/release/build_bys360_safe_release.py --verify <path-to-zip> --expected-source-sha <sha>
```

This re-hashes every file actually inside the ZIP and compares it against the recorded
`sha256sums.txt`, cross-checks that the recorded hash set matches the manifest's own `files`
list exactly (catching a manifest/sha256sums pair that has drifted apart), confirms no
forbidden path (a real `.env`, an `instance/` file, a `.sqlite3`/`.dump`/`.key`/etc.) is
present in the ZIP regardless of what the manifest claims, confirms none of
`tests/`, `mobile_flutter/`, `.codex/`, `.claude/` appear anywhere in the package, and — if
`--expected-source-sha` is supplied — confirms the manifest's own `source_sha` matches what
you expected to receive. It prints a JSON result with an `ok` boolean and a `findings` list,
and exits non-zero on any finding. **Do not skip this step and trust the ZIP's filename
alone** — a filename is not a hash.

## 2. Manifest schema check

At minimum, confirm the sidecar manifest has:

- `"schema_version": 2` (or whatever the actually-shipped builder version produces — a
  mismatch here means you may be looking at output from an older or newer, differently
  structured builder, and should not assume field-for-field compatibility with what this
  document describes).
- A `source_sha` that is a 40-character lowercase hex string.
- An `included_count` that matches `len(files)`.
- A `files` list that includes, at minimum, every path under
  `REQUIRED_PACKAGE_PATH_PREFIXES` (`app/`, `migrations/`, `requirements.txt`, `wsgi.py`,
  `run_server.py`, `config.py`, `DEPLOYMENT.md`) — the verify command above already checks
  this, but it is worth understanding *why* it checks it: a package missing any of these
  cannot possibly run as a working application.

## 3. File-count check

Compare the manifest's `included_count` against whatever count the release was announced
with out of band (release notes, a handover email, a prior FULL package's own count as a
sanity baseline). A large, unexplained discrepancy — especially a *smaller* count than
expected — is a signal worth investigating before use, even if the SHA256/manifest
cross-check above technically passes (a shrunk-but-internally-consistent package is exactly
what an internally-consistent-but-wrong build would look like). The historical deployment
script's own `$ExpectedPackageFileCount` parameter (defaulted to `2140` for the `ec4e56b`
release) is the direct model for pinning an expected count per release, rather than trusting
whatever count happens to be in the manifest being verified.

## 4. Clean-room acceptance procedure

"Clean-room" here means: verify the package using nothing but the package itself, the
documented external secrets/configuration, and the tooling in this repository — no access
to the machine that built it, no trust in claims made outside the package's own
cryptographically-checkable contents.

1. Run the SHA256/manifest verification (section 1) on a machine that did **not** build the
   package.
2. Extract the ZIP to a scratch directory (not `C:\bys360\candidate\` yet — a true clean-room
   check happens before you commit to using this package for a real candidate).
3. Run `scripts/release/scan_bys360_release_secrets.py` (see below) against the extracted
   contents. A clean release must produce zero findings.
4. Confirm the required top-level paths exist and are non-empty:
   `app/`, `migrations/`, `requirements.txt`, `wsgi.py`, `run_server.py`, `config.py`,
   `DEPLOYMENT.md`.
5. Confirm the migration graph inside the package has a single head, using the same
   `flask db heads` check documented in `DATABASE_MIGRATION.md`, run against the *extracted
   package's own* `migrations/` directory (borrowing a currently-installed Python
   environment's Alembic/Flask, as the historical script's staging-verification step does —
   see `CANDIDATE_PREPARATION.md` for why this borrowing is necessary before a candidate's
   own venv exists).
6. Only after all of the above pass, proceed to actual candidate preparation
   (`CANDIDATE_PREPARATION.md`), which performs its own additional, deeper verification
   (dependency install, shadow migration rehearsal, health boot) against a real running
   application, not just static file contents.

## 5. What "handover-ready" actually means as a claim

"Handover-ready" is not a single boolean and should never be asserted as one without
evidence behind every part of it. It means, specifically and only:

- The release package passes SHA256/manifest/schema/file-count verification (this
  document, sections 1–3).
- The package contains zero real secrets (section 4, step 3 — a clean scanner run).
- The documented external prerequisites (`LIVE_INSTALLATION.md`) are actually present on
  the target host, not merely assumed.
- A candidate built from this package actually reaches `CANDIDATE_READY.json`
  (`CANDIDATE_PREPARATION.md`) — including a successful shadow migration rehearsal and a
  successful health boot — on the actual target host, not merely "should work in theory."
- The operator documentation set (this file and its seven siblings under
  `docs/handover/`) accurately describes the actually-integrated scripts, verified against
  those scripts directly, not only against the specification they were written from.

A claim of "handover-ready" that skips any of the above — especially direct comparison
with the maintained scripts — is not evidence-backed and should not be made. See the
Devredilebilirlik Gate rubric below for how to score readiness category-by-category instead
of as a single undifferentiated claim.

---

## Devredilebilirlik Gate — Scoring Rubric

This section defines **how** to score BYS360's deployment-transferability readiness across
eight independent categories. It intentionally does not contain any actual scores — scoring
requires evaluating the integrated system and its test evidence. The maintained
[preparation](../../scripts/windows/prepare_bys360_candidate.ps1),
[cutover](../../scripts/windows/cutover_bys360_candidate.ps1), and
[rollback](../../scripts/windows/rollback_bys360_candidate.ps1) scripts are present in the
repository. Their presence alone does not establish readiness; score each claim only
against the actual source revision, delivered artifacts and verification evidence.

**Any critical category below acceptable production level means: DO NOT DECLARE FINAL FULL
READY. Do not inflate the existing transferability score. Evidence only — a category is not
"probably fine," it either has the evidence described below or it does not.**

For each category: what "acceptable production level" concretely means, what evidence would
prove it, and what would fail it.

### 1. SOURCE HANDOVER

- **Acceptable level**: the release package's `source_sha` is independently verifiable
  against the actual git history (not just self-consistent within the package), and an
  operator with no GitHub access can determine exactly what commit is running without
  needing to trust an unverifiable claim.
- **Evidence**: a successful `--verify --expected-source-sha` run (section 1 above) against
  a SHA the operator obtained from a source independent of the package itself (a signed
  handover email, a separate manifest delivered out of band); confirmation that the package
  contains no `.git/` directory (so it cannot be tampered with and re-signed internally) and
  that `git diff <claimed-previous-sha>..<claimed-sha> --stat`, run on a development machine
  with real git history, matches what the release notes claim changed.
- **Fails if**: the only evidence of source identity is the ZIP's filename, or the manifest
  is trusted without independent SHA confirmation, or `.git` history needed to verify the
  claim is unavailable to the operator entirely.

### 2. DEPENDENCY HANDOVER

- **Acceptable level**: every dependency, direct and transitive, is installable on the
  target host with zero PyPI/network access, using only artifacts shipped with the release.
- **Evidence**: a real `pip install --no-index --find-links wheelhouse -r requirements.lock`
  run, on the actual target host (or a faithful clone of it), completing with exit code 0,
  producing a venv that can actually import the application (`python -c "from app import
  create_app; create_app()"` succeeding, or the candidate's own health-boot check passing).
- **Fails if**: the install only "worked" on a machine that happened to still have network
  access, or `requirements.lock` doesn't actually match what `build/wheelhouse/` contains
  (a lock/wheelhouse drift), or the install was never actually attempted offline.

### 3. DATABASE HANDOVER

- **Acceptable level**: a documented, current migration head; a proven, repeatable shadow
  rehearsal procedure that runs the real migration against a real copy of production data
  under the real application role's real privileges; a verified File Center table count
  post-migration.
- **Evidence**: the exact commands and exact observed output for `flask db heads` /
  `flask db current` against the actual release being evaluated (not copied from a prior
  release without re-running — see `DATABASE_MIGRATION.md` for the standard this document
  itself was held to); a real shadow-rehearsal run reaching `exit_code=0` on restore and
  migration, with the target revision and 19-table (or whatever the current true count is)
  count both confirmed.
- **Fails if**: the migration head or table count is asserted without a fresh command run
  against the actual system being scored, or shadow rehearsal has never actually been
  executed end-to-end on real production-shaped data.

### 4. OPERATIONS HANDOVER

- **Acceptable level**: an operator with no tribal knowledge can install prerequisites, run
  candidate preparation, run cutover, verify success, and know what to do on failure, using
  only this document set and the actual scripts — no Slack history, no developer
  availability required.
- **Evidence**: a genuine dry run (or, ideally, a real cutover) performed by someone who did
  not write the scripts, following only the documentation, successfully reaching a healthy
  post-cutover state; every ambiguity or missing step they hit along the way logged and
  fixed in the docs.
- **Fails if**: the only people who have ever successfully run these scripts are the people
  who wrote them, or the documentation contains placeholder/unverified claims (like the
  "verify against the actually integrated script" caveats scattered through this document
  set, if they are still unresolved at scoring time).

### 5. DEPLOYMENT HANDOVER

- **Acceptable level**: candidate preparation and cutover work as designed — candidate
  build/verify never touches the live service, cutover's live-affecting window is short and
  bounded, and every phase fails closed with an actionable receipt.
- **Evidence**: a real end-to-end candidate-prep-then-cutover run, with timestamps showing
  the actual downtime window achieved (steps 6–15 of `CUTOVER.md`, ideally measured in
  seconds/low minutes, not the unbounded time a preparation failure could have cost in the
  old model); receipts from at least one deliberately-induced failure at each major phase,
  confirming the live service was left in the expected, documented state each time.
- **Fails if**: cutover has only ever been tested on the success path, or a preparation-phase
  failure has ever been observed to affect the live service in any way (which would indicate
  the isolation this whole redesign depends on is not actually holding).

### 6. ROLLBACK HANDOVER

- **Acceptable level**: pre-migration rollback is proven trivial; post-migration rollback
  safety is evaluated per-release via a real source diff, never assumed; DB backups are
  confirmed never deleted by any rollback path.
- **Evidence**: a real rollback performed after a deliberately-failed cutover, in both the
  pre-migration and post-migration cases, confirming the application actually comes back
  healthy in each; confirmation that the backup file from the failed attempt is still present
  on disk after rollback completes.
- **Fails if**: post-migration rollback safety is asserted as a blanket property ("code
  rollback is always safe here") rather than checked per release, or rollback has never
  actually been exercised against a real post-migration failure, or any backup is found
  missing after a rollback that should not have touched it.

### 7. DOCUMENTATION HANDOVER

- **Acceptable level**: this document set (and its seven siblings) accurately describes the
  actually-integrated scripts — exact function/parameter/phase names verified against real
  code, not only against the shared specification they were originally written from.
- **Evidence**: a line-by-line reconciliation pass, performed after all three parallel work
  streams are integrated, checking every "verify against the actually integrated script"
  caveat in this document set against the real, merged `prepare_bys360_candidate.ps1` /
  `cutover_bys360_candidate.ps1` / `rollback_bys360_candidate.ps1`, with any discrepancy
  either fixed in the docs or flagged as a real script defect.
- **Fails if**: this reconciliation pass has not happened, or has happened but left known
  discrepancies undocumented.

### 8. SECRET SEPARATION

- **Acceptable level**: zero real secrets anywhere in the release package, the wheelhouse,
  or the documentation tree; every secret an operator needs is sourced from the live host's
  existing `.env`/credentials, never shipped.
- **Evidence**: a clean (`ok: true`, zero findings) run of
  `scripts/release/scan_bys360_release_secrets.py` against the actual release ZIP's
  extracted contents, the actual `build/wheelhouse/` directory, and the actual
  `docs/handover/` tree — see the relevant secret-scan report for this repository's current
  state, reported separately rather than restated here as a
  permanent claim, since it must be re-run against every new release, not assumed to still
  hold.
- **Fails if**: the scanner has never been run against the actual artifact being handed
  over, or it has findings that were dismissed without individual investigation (see the
  scanner's own documented false-positive rate — a finding must be individually confirmed as
  a false positive, never bulk-dismissed).
