# Contributing to PreflightOps

Thanks for considering a contribution.

PreflightOps is an open-source pre-deployment risk assessment toolkit for SRE, DevOps, Platform Engineering, and Cloud Operations teams.

The project is intentionally lightweight: clear rules, readable code, transparent scoring, and practical outputs.

---

## Ways to contribute

Good contributions include:

- New risk rules
- Better Terraform scanner signals
- Better Kubernetes scanner signals
- New example scenarios
- Documentation improvements
- Bug fixes
- Test coverage
- GitHub Action improvements
- Report formatting improvements

---

## Local setup

```bash
git clone https://github.com/pedroluna-gh/preflightops.git
cd preflightops
uv sync --locked --all-extras --group quality
uv run pytest
```

Before opening a pull request, reproduce every mandatory check in
[`docs/QUALITY_GATES.md`](docs/QUALITY_GATES.md).

Run the web app:

```bash
streamlit run app.py
```

Run the CLI:

```bash
preflightops \
  --services examples/services-high-risk.yaml \
  --change examples/change-high-risk.yaml \
  --output report.md
```

---

## Code style

Please keep the code:

- readable;
- explicit;
- dependency-light;
- well-commented where operational intent matters;
- covered by tests when behavior changes.

This project is meant to be understandable by SREs, platform engineers, DevOps engineers, engineering managers, and operations leaders.

---

## Adding a new risk rule

When adding a rule:

1. Add the rule logic.
2. Give it a stable `id`.
3. Add a clear description.
4. Assign a severity: `low`, `medium`, `high`, or `critical`.
5. Assign a score.
6. Add or update tests.
7. Update documentation if needed.

Rule example:

```python
{
    "id": "missing-rollback-plan",
    "description": "Production change has no valid rollback plan",
    "severity": "high",
    "score": 30,
    "source": "Service Controls",
}
```

---

## Adding scanner signals

Scanner signals should be practical and explainable.

Avoid overly broad keywords that create too many false positives.

Good signals:

- IAM changes
- Database changes
- Destroy/delete actions
- LoadBalancer exposure
- Secrets
- Missing readiness/liveness probes

---

## Pull request checklist

Before opening a PR:

- [ ] The frozen lockfile installs without drift
- [ ] Formatting, lint and type checks pass
- [ ] Tests pass with the coverage floor
- [ ] Dependency audit passes without an unreviewed suppression
- [ ] Package build, clean installation, CLI and action contract pass
- [ ] New behavior has tests
- [ ] Documentation updated if needed
- [ ] Example files still work
- [ ] No secrets, customer data, or internal company information included

---

## Security note

Do not include real production secrets, credentials, customer data, internal hostnames, private incident data, or proprietary runbooks in examples or tests.
