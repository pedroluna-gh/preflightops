# Dependency security maintenance — 2026-11-21

## Scope and decision

PR #53 originally updated urllib3 only. A fresh audit of the complete locked
runtime/extras and development toolchain found additional advisory matches.
The change addresses those matches without disabling scanners or adding
security exceptions. Assessment algorithms, legacy outputs and integration
permissions are unchanged. No external integration is exercised by validation.

| Dependency | Previous | Corrected | Reason |
| --- | --- | --- | --- |
| urllib3 | 2.7.0 | 2.8.0 | HTTPS proxy TLS and chunked-streaming security fixes |
| certifi | 2026.7.22 | 2026.10.18 | Advisory reported by the current dependency audit |
| filelock | 3.32.4 | 4.2.1 | Advisory matches in the development toolchain |
| msgpack | 1.2.2 | 1.2.3 | Advisory match in the development toolchain |
| Pillow | 12.3.0 | 13.0.0 | Image-decoding advisory matches in the optional UI |
| pyasn1 | 0.6.4 | 0.6.5 | Advisory matches in the optional authentication dependencies |
| setuptools | 83.0.0 | 84.1.0 | Advisory match; build backend and quality pin remain identical |
| Streamlit | 1.62.0 | 1.67.0 | Resolver-required compatibility with Pillow 13 |

The resolver also removes unused blinker, httptools and toml distributions.
Other dependency versions remain locked. urllib3's upstream
[release notes](https://github.com/urllib3/urllib3/releases/tag/2.8.0) describe
the TLS behavior change and the streaming fixes. Proxy configurations relying
on destination TLS settings also applying to the proxy need explicit review.

## Local verification

Environment: Windows, Python 3.12.13, uv 0.12.1; a separate environment was
installed from the exact lock with all extras and the quality group.

- Runtime/extras and complete toolchain exports: pip-audit 2.10.1 returned
  zero known vulnerabilities for packages applicable to this environment.
  This is a dated advisory lookup, not a claim that the product has no flaws.
- Ruff formatting and lint passed for all 100 maintained Python files;
  mypy passed for 38 source files.
- Full suite: 1,206 tests passed, including the 42 UI behavior tests;
  branch-aware coverage was 87.19%, above the required 85%.
- OpenSpec strict validation: 11 specifications passed.
- Wheel and canonical sdist were built twice from fresh source snapshots;
  both builds produced byte-identical artifacts. Twine checks passed.
- The wheel was installed in an empty environment; public CLI LOW and
  CRITICAL scenarios returned their expected exit codes and produced reports.
- The complete lock SBOM was generated and its inventory verified.
- The license record accepts the exact updated lock in development and
  correctly rejects publication while approval remains pending.

Lock SHA-256 after LF normalization:
`7c2560010c779c1f8dc505668b9d8bf61ab03a1f52772184f43ddea5ea1a7a7b`.

Local reproducibility hashes (not authenticated release provenance):

- wheel: `2d67da3f42ddc6d12348703770aa0f08ee166f99a44a663317bf450400309532`
- sdist: `db159838571cf4cedfb24666449b36036cdefec4b1d9491d8c0b5de52ad0e8f0`

## Remote exit gate

Before merge, the final PR head must pass Required, every compatibility and
dependency-audit job, CodeQL, dependency review and the remaining triggered
checks. Record links to that head and its CI runs in the PR closure evidence.
Old successful runs do not validate this dependency set.

## Residual risk and rollback

License approval remains pending; this change does not authorize a release.
Platform-specific dependencies require the CI Python/OS matrix. Advisory
coverage is limited by the databases and package metadata available at audit
time. The optional UI framework upgrade is covered by its existing behavior
tests, including example loading, reports and integration simulations.

If a regression occurs, disable the affected optional integration or UI and
prepare a reviewed corrective PR. Reverting the dependency commit restores
known-vulnerable versions and is not an acceptable steady state: any emergency
revert must be documented, time-bounded, and paired with isolation of the
affected path. Restore pyproject.toml, uv.lock and the license binding together;
never bypass the audit or license-publication gates to make rollback green.

Stage 16 implementation and major CI-action/tooling upgrades are separate
changes. No production deployment or release publication is part of this PR.
