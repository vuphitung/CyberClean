# CyberClean 3.2.0 --- Engineering Improvement Plan

**Document type:** Release hardening / technical roadmap\
**Target version:** CyberClean 3.2.0\
**Priority:** Safety, recoverability, security, release confidence\
**Status:** Proposed plan based on the initial review of
`CyberClean.zip`

------------------------------------------------------------------------

## 1. Release objective

CyberClean 3.2.0 should prioritize making existing system-level
operations safer and more recoverable rather than adding many new
features.

The release should aim to:

1.  Prevent unintended deletion when filesystem objects change during a
    cleanup operation.
2.  Recover system settings reliably if Boost is interrupted, the
    application crashes, or the machine loses power.
3.  Strengthen the trust chain from installer download through
    privileged installation and update.
4.  Reduce unnecessary privilege exposure.
5.  Establish repeatable automated tests and release checks on Windows
    and Linux.

**Release principle:** No cleanup or optimization feature should leave
the operating system in a worse state when an operation fails halfway
through.

## 2. Priority overview

  ----------------------------------------------------------------------------------
  ID             Priority       Area            Improvement        Release gate
  -------------- -------------- --------------- ------------------ -----------------
  CC32-01        P0             Boost recovery  Durable            Must pass
                                                write-ahead        crash-injection
                                                recovery journal   tests

  CC32-02        P0             Windows cleaner Handle-based       Must pass
                                                deletion and       race-condition
                                                reparse-point      tests
                                                protection         

  CC32-03        P1             Installer       Authenticate the   Must verify
                                security        bootstrap          before privileged
                                                installer          execution

  CC32-04        P1             Privileged      Review             Must pass
                                helper          sudoers/Polkit     authorization
                                                authorization      tests
                                                boundary           

  CC32-05        P1             CI/testing      Automated          Required checks
                                                Windows/Linux test must pass
                                                matrix             

  CC32-06        P1             Build system    Remove             Clean build on
                                                machine-specific   another machine
                                                paths from         
                                                packaging          

  CC32-07        P2             Architecture    Split oversized    No behavior
                                                modules by         regression
                                                responsibility     

  CC32-08        P2             Observability   Structured         Logs must not
                                                operation and      expose secrets
                                                recovery logs      

  CC32-09        P2             Documentation   Publish support    Documentation
                                                matrix and safety  matches tested
                                                limitations        behavior

  CC32-10        P2             Release process Reproducible       Release
                                                artifacts,         verification
                                                checksums and      succeeds
                                                signatures         
  ----------------------------------------------------------------------------------

P0 items are release blockers for the affected functionality. If they
are not completed, disable or clearly restrict the affected feature
rather than shipping it as fully safe.

------------------------------------------------------------------------

## 3. Detailed work items

### CC32-01 --- Make Boost recovery crash-safe

**Priority:** P0\
**Relevant files:** `core/booster.py`, `core/game_boost_widget.py`

#### Current concern

The existing implementation has state persistence and stale-state
recovery mechanisms, which is a good foundation. However, state
persistence is not consistently guaranteed before every system mutation.
A direct JSON `write_text()` operation can also be interrupted and leave
an incomplete state file.

Cleanup callbacks are useful for normal shutdown, but they cannot be
relied on for hard crashes, forced termination, kernel failure or power
loss.

#### Required improvements

1.  Capture the original state of every setting before changing it.
2.  Persist a write-ahead journal before the first system mutation.
3.  Write journal updates using a temporary file in the same directory,
    flush, `fsync`, and atomic replacement.
4.  Record each operation with a stable ID, target, original value,
    intended value and status.
5.  Mark an operation complete only after verifying the resulting system
    state.
6.  On startup, detect incomplete transactions and offer or perform safe
    recovery according to a documented policy.
7.  Make restoration idempotent: running recovery more than once must
    not cause additional damage.
8.  Preserve the journal until recovery is verified; do not delete it
    merely because a restore command was attempted.
9.  Handle partial failure: report which settings were restored and
    which require manual intervention.
10. Ensure concurrent Boost sessions cannot overwrite each other's
    state.

#### Suggested journal model

-   `schema_version`
-   `transaction_id`
-   `created_at`
-   `updated_at`
-   `platform`
-   `application_version`
-   `status`: `prepared`, `applying`, `restoring`, `recovered`,
    `needs_attention`
-   `operations[]`:
    -   `operation_id`
    -   `subsystem`
    -   `target`
    -   `original_value`
    -   `requested_value`
    -   `status`
    -   `last_error`

Do not store credentials, tokens or other secrets in the journal.

#### Acceptance tests

-   Kill the application after each individual system mutation.
-   Simulate a failed journal write.
-   Simulate a failed system mutation.
-   Restart after an incomplete transaction.
-   Run recovery twice and verify idempotency.
-   Verify that a failed restore retains enough information for
    diagnosis.
-   Verify that a new Boost session cannot start while an unresolved
    transaction exists, unless an explicit safe policy allows it.

**Definition of done:** Every Boost mutation is preceded by durable
recovery information, and crash-injection tests demonstrate recovery or
a clear `needs_attention` state.

------------------------------------------------------------------------

### CC32-02 --- Harden Windows cleanup against filesystem races

**Priority:** P0\
**Relevant file:** `core/engine.py`, especially
`_remove_tree_windows_verified()`

#### Current concern

The Windows deletion path relies on path-based checks followed by
path-based deletion. An object may be replaced between validation and
deletion (a TOCTOU race). Reparse points and junctions also require
careful handling.

#### Required improvements

1.  Use Windows file handles to identify and operate on the validated
    filesystem object.
2.  Open objects with reparse-point-aware flags and inspect their
    attributes and final identity.
3.  Verify volume and file identity using handle-based metadata where
    supported.
4.  Refuse unexpected reparse points, junctions, mount points and device
    paths.
5.  Revalidate the object immediately before deletion.
6.  Avoid following links during recursive traversal.
7.  Ensure cleanup roots are canonicalized and constrained to explicitly
    approved locations.
8.  Fail closed when identity verification is unavailable or ambiguous.
9.  Keep dry-run and preview behavior aligned with actual execution
    behavior.
10. Record skipped objects and reasons without exposing sensitive file
    contents.

Implementation should use a carefully reviewed Windows API wrapper
rather than scattered low-level calls throughout the cleaner.

#### Acceptance tests

-   Replace a directory with a junction between scan and delete.
-   Replace a file with a symlink/reparse point between validation and
    delete.
-   Attempt traversal outside the approved cleanup root.
-   Test locked files, access denied, long paths and Unicode paths.
-   Test mount points and volume boundaries.
-   Confirm that a race causes a safe skip, not deletion of an
    unexpected target.

**Definition of done:** Windows cleanup uses object identity and
reparse-point protections, and adversarial race tests demonstrate safe
failure.

------------------------------------------------------------------------

### CC32-03 --- Secure the installer bootstrap

**Priority:** P1\
**Relevant file:** `install.sh`

#### Current concern

The installer bootstrap is downloaded and executed with elevated
privileges. Verifying the application package later in the script does
not authenticate the bootstrap script that has already begun running.

#### Required improvements

1.  Publish a signed installer or a small independently verifiable
    bootstrap.
2.  Document how users obtain the trusted public key.
3.  Verify the installer signature before running privileged operations.
4.  Pin trusted release metadata and reject unsigned or invalid
    metadata.
5.  Avoid executing mutable content from a branch such as `main` as
    root.
6.  Use secure temporary directories and restrictive file permissions.
7.  Validate archive paths before extraction to prevent path traversal.
8.  Ensure failed verification stops installation immediately.
9.  Document key rotation and compromised-key response.
10. Keep installation logs useful but free of secrets.

#### Acceptance tests

-   Modified installer must fail verification.
-   Modified release metadata must fail verification.
-   Invalid or unknown signing key must fail closed.
-   Archive containing path traversal entries must be rejected.
-   Interrupted installation must not leave unsafe permissions or
    partially trusted binaries.

**Definition of done:** The bootstrap is authenticated before privileged
execution, and tampering tests fail safely.

------------------------------------------------------------------------

### CC32-04 --- Reduce privileged-helper exposure

**Priority:** P1\
**Relevant files:** `packaging/cyber-clean-helper`,
`core/privileged.py`, installer authorization configuration

#### Current concern

The helper already uses an allowlist-oriented design, which is
preferable to accepting arbitrary shell commands. However, a broad
passwordless sudo rule increases the impact of any vulnerability in the
helper or its argument validation.

#### Required improvements

1.  Review every helper action and classify its risk.
2.  Keep the action allowlist narrow and reject unknown actions.
3.  Validate argument types, lengths, paths and package identifiers at
    the privileged boundary.
4.  Never pass user-controlled strings to a shell.
5.  Consider Polkit for interactive authorization of sensitive actions.
6.  If sudoers remains supported, use the narrowest feasible command and
    argument policy.
7.  Ensure helper binaries and parent directories are not writable by
    unprivileged users.
8.  Protect against symlink replacement of helper configuration and
    executable paths.
9.  Add authorization audit events for sensitive operations.
10. Ensure helper errors do not leak secrets or internal environment
    data.

#### Acceptance tests

-   Unknown action is rejected.
-   Extra or malformed arguments are rejected.
-   Shell metacharacters are treated as data, never commands.
-   Untrusted paths and symlink swaps are rejected.
-   Unauthorized users cannot perform privileged actions.
-   Helper cannot be replaced or modified by an unprivileged account.

**Definition of done:** Every privileged operation has a documented
authorization rule and negative tests proving unauthorized requests are
rejected.

------------------------------------------------------------------------

### CC32-05 --- Establish a cross-platform CI test matrix

**Priority:** P1

#### Required improvements

Create automated CI workflows that run on clean environments.

Suggested matrix:

  -----------------------------------------------------------------------
  Platform                Python                  Required checks
  ----------------------- ----------------------- -----------------------
  Ubuntu Linux            Supported project       Compile, lint, unit
                          version(s)              tests, helper tests

  Windows                 Supported project       Compile, lint, unit
                          version(s)              tests, cleaner safety
                                                  tests

  macOS                   Supported project       Compile, lint, portable
                          version(s), if          unit tests
                          officially supported    
  -----------------------------------------------------------------------

The exact Python versions and operating-system versions must match the
project's declared support policy.

#### CI stages

1.  Dependency installation from pinned or constrained dependencies.
2.  Python compile check.
3.  Lint and formatting checks.
4.  Unit tests.
5.  Platform-specific tests.
6.  Security-focused tests.
7.  Build/package smoke test.
8.  Artifact and signature verification.

GUI tests should run with the required Qt dependencies and a suitable
headless display strategy where appropriate.

#### Acceptance tests

-   CI runs from a clean checkout.
-   A missing dependency causes a clear failure.
-   Test skips are reported with reasons.
-   Platform-specific tests are not silently skipped on the platform
    they are intended to validate.
-   Release branches cannot publish artifacts when required checks fail.

**Definition of done:** A clean checkout can be tested and built through
documented automated workflows on every officially supported platform.

------------------------------------------------------------------------

### CC32-06 --- Make packaging independent of the developer's machine

**Priority:** P1\
**Relevant file:** `CyberClean.spec`

#### Current concern

The spec file contains a developer-machine-specific absolute Windows
path for the icon. This can break builds on another machine.

#### Required improvements

1.  Resolve assets relative to the spec file's directory.
2.  Validate that required assets exist before starting the build.
3.  Keep build configuration out of personal user directories.
4.  Pin build dependencies.
5.  Build in a clean environment.
6.  Record build version, commit identifier and dependency versions.
7.  Test the produced package on a clean machine or VM.

#### Acceptance tests

-   Build succeeds after moving the repository to a different directory.
-   Build succeeds on a second Windows machine or clean CI runner.
-   Missing assets produce a clear error.
-   No personal absolute paths remain in packaging configuration.

**Definition of done:** The release package can be built from a clean
checkout without relying on the original developer's filesystem.

------------------------------------------------------------------------

### CC32-07 --- Refactor oversized modules incrementally

**Priority:** P2\
**Relevant files:** `core/booster.py`, `main.py`, `ui_widgets.py`,
`core/game_boost_widget.py`, `utils/i18n.py`, `core/engine.py`

#### Suggested direction

  Existing responsibility          Suggested module boundary
  -------------------------------- ------------------------------
  CPU scheduling and priority      `core/boost/cpu.py`
  GPU settings and detection       `core/boost/gpu.py`
  Service management               `core/boost/services.py`
  Boost state and recovery         `core/boost/recovery.py`
  Platform-specific cleanup        `core/cleaner/platform/`
  Cleanup planning and execution   `core/cleaner/engine.py`
  UI presentation                  `ui/` or existing UI package

These are suggested boundaries, not mandatory filenames.

#### Rules

-   Do not combine a large refactor with a safety-critical behavior
    change.
-   Preserve public interfaces while extracting modules.
-   Add regression tests before moving code.
-   Keep platform-specific operations behind explicit interfaces.
-   Avoid circular imports.

**Definition of done:** Each extracted module has a clear responsibility
and the existing regression suite remains green.

------------------------------------------------------------------------

### CC32-08 --- Improve logs and diagnostics

**Priority:** P2

#### Required improvements

1.  Use structured logs with timestamp, severity, component and
    operation ID.
2.  Record cleanup decisions: planned, skipped, completed and failed.
3.  Record Boost transaction and recovery outcomes.
4.  Distinguish user cancellation, permission denial, unsupported
    operation and internal failure.
5.  Add log rotation and bounded disk usage.
6.  Redact secrets, tokens, personal paths and sensitive command
    arguments where appropriate.
7.  Provide an exportable diagnostic report with user consent.

**Definition of done:** A failed operation can be diagnosed from logs
without exposing sensitive user data.

------------------------------------------------------------------------

### CC32-09 --- Clarify support and safety documentation

**Priority:** P2

Update documentation to state:

-   Officially supported operating systems and versions.
-   Supported Python versions.
-   Which features are read-only and which modify the system.
-   Which actions require Administrator/root privileges.
-   What Boost changes and how restoration works.
-   What cleanup categories can and cannot be safely removed.
-   Known limitations for Windows reparse points and Linux filesystem
    behavior.
-   How to recover after an interrupted operation.
-   How signatures and trusted keys are verified.
-   Which tests run in CI and which require real hardware.

Do not describe a feature as fully tested on a platform unless it has
actually been exercised there.

------------------------------------------------------------------------

### CC32-10 --- Formalize the release process

**Priority:** P2

#### Required release checklist

-   [ ] Version and changelog updated.
-   [ ] Clean CI matrix passes.
-   [ ] P0 safety tests pass.
-   [ ] Installer bootstrap signature verifies.
-   [ ] Application package signature verifies.
-   [ ] Checksums generated and published.
-   [ ] Windows package installed and launched in a clean VM.
-   [ ] Linux package installed and launched in a clean VM.
-   [ ] Upgrade from the previous supported version tested.
-   [ ] Uninstall tested.
-   [ ] Recovery after interrupted Boost tested.
-   [ ] No secrets, local paths or development artifacts included.
-   [ ] Known limitations documented.
-   [ ] Rollback/revocation procedure documented.

------------------------------------------------------------------------

## 4. Recommended implementation order

### Sprint 1 --- Safety and recovery

-   CC32-01: Boost recovery journal.
-   CC32-02: Windows cleaner hardening.
-   Add crash-injection and filesystem race tests.
-   Temporarily disable unsafe paths if a fix cannot be completed.

### Sprint 2 --- Privilege and supply-chain security

-   CC32-03: Installer bootstrap authentication.
-   CC32-04: Privileged helper authorization review.
-   Add tampering and authorization tests.

### Sprint 3 --- Repeatable builds and quality gates

-   CC32-05: Cross-platform CI.
-   CC32-06: Portable packaging.
-   Add clean VM smoke tests.

### Sprint 4 --- Maintainability and release readiness

-   CC32-07: Incremental module extraction.
-   CC32-08: Structured diagnostics.
-   CC32-09: Documentation.
-   CC32-10: Release checklist and final validation.

Sprint boundaries can be adjusted to the available development time. Do
not defer P0 safety work in favor of UI polish or new optimization
features.

------------------------------------------------------------------------

## 5. Release acceptance criteria

CyberClean 3.2.0 should not be declared production-ready until all
applicable criteria below are met:

1.  **Boost recovery:** Every system mutation has durable recovery
    information written before execution.
2.  **Crash safety:** Forced termination at each transaction stage
    results in verified restoration or a clear manual-recovery state.
3.  **Windows deletion safety:** Reparse-point and race-condition tests
    demonstrate that cleanup cannot escape approved roots.
4.  **Privilege boundary:** Every helper action is allowlisted,
    validated and authorization-tested.
5.  **Installer integrity:** The bootstrap and application artifacts are
    authenticated before privileged installation.
6.  **Cross-platform quality:** Required CI checks pass on all
    officially supported platforms.
7.  **Build portability:** A clean checkout builds without
    developer-specific absolute paths.
8.  **Operational visibility:** Failures and recovery outcomes are
    diagnosable without leaking secrets.
9.  **Documentation accuracy:** Every platform and feature claim is
    supported by actual test evidence.
10. **Release rollback:** A failed update or installation has a
    documented recovery path.

A feature that does not meet its safety criteria should be disabled,
restricted or clearly marked experimental in 3.2.0.

------------------------------------------------------------------------

## 6. Scope control --- what should not be prioritized in 3.2.0

To keep this release focused, defer the following unless they are
required to fix a confirmed defect:

-   Major visual redesign.
-   New optimization toggles.
-   More aggressive automatic cleanup categories.
-   Large-scale rewrite of the application.
-   Unnecessary framework migration.
-   Performance claims without repeatable benchmarks.

The goal of 3.2.0 is not to have the most features. It is to make the
existing features safer, predictable and verifiable.

## 7. Final recommendation

Treat CyberClean 3.2.0 as a **stability and security release**.

The first two engineering tasks should be:

1.  Make Boost recovery durable and crash-safe.
2.  Make Windows deletion operate on verified filesystem objects rather
    than relying only on path-based checks.

After those are addressed, harden the installer and privileged helper,
then establish CI and clean-machine release testing.

**Suggested release message:**\
"CyberClean 3.2.0 focuses on system-operation safety, crash recovery,
installer integrity, privilege boundaries and cross-platform
reliability."

------------------------------------------------------------------------

**Important review note:** This plan is based on the initial source
review and test execution available for the supplied ZIP. It is an
engineering action plan, not a claim that every listed issue is
exploitable or that the proposed fixes have already been implemented.
Re-test each item against the exact 3.2.0 source and supported operating
systems before release.
