"""Coverage-guided fuzz target for trust-boundary validators."""

import sys

import atheris

with atheris.instrument_imports():
    import json

    from preflightops.integration_errors import IntegrationError
    from preflightops.monitoring import validate_monitoring_evidence
    from preflightops.servicenow import load_mapping, validate_instance_url


def test_one_input(data: bytes) -> None:
    """Exercise URL, mapping, and observability validators without network I/O."""

    provider = atheris.FuzzedDataProvider(data)

    candidate_url = provider.ConsumeUnicodeNoSurrogates(512)
    try:
        validate_instance_url(candidate_url, env={})
    except IntegrationError:
        pass

    document = provider.ConsumeUnicodeNoSurrogates(8192)
    try:
        payload = json.loads(document)
    except (json.JSONDecodeError, RecursionError):
        return
    if not isinstance(payload, dict):
        return

    mapping = payload.get("mapping")
    if isinstance(mapping, dict):
        try:
            load_mapping(mapping)
        except IntegrationError:
            pass

    change = payload.get("change")
    policy = payload.get("policy")
    if isinstance(change, dict) and (policy is None or isinstance(policy, dict)):
        try:
            validate_monitoring_evidence(
                change,
                inventory=payload.get("inventory"),
                policy=policy,
            )
        except ValueError:
            pass


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
