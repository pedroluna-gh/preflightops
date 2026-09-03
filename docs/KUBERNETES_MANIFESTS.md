# Kubernetes manifest analysis

PreflightOps evaluates supplied Kubernetes YAML as an offline, bounded and
deterministic document set. It never contacts a cluster, resolves Helm or
Kustomize templates, or treats comments and arbitrary text as evidence.

## Input contract

`scan_kubernetes()` and the CLI `--k8s` path accept UTF-8 YAML containing one
or more Kubernetes objects. Every evaluated object requires non-empty
`apiVersion`, `kind`, `metadata.name` and a textual namespace; an absent
namespace is normalized to `default`. Empty YAML documents are ignored and a
`kind: List` is expanded into independent objects.

The default `KubernetesManifestLimits` bounds processing before findings are
returned:

| Boundary | Default |
| --- | ---: |
| Input | 4 MiB |
| YAML documents | 256 |
| Alias references | 128 |
| Graph depth | 64 |
| Unique nodes per document | 100,000 |
| Expanded objects | 2,048 |
| Containers and init containers | 8,192 |
| String or mapping-key length | 1 MiB |

The safe loader rejects duplicate or non-string keys, YAML merge keys, unsafe
tags, recursive aliases, non-finite numbers and non-JSON scalar types. Object
identity duplicates are rejected. Containers must be mappings with names.
Any violation raises a content-safe `KubernetesManifestError` and produces no
partial result. The CLI exits `2` before writing reports; errors never become a
LOW/PASS assessment and never activate the legacy scanner automatically.

## Structural evidence

Every finding identifies:

- `resource` as the compact `kind/name` reference retained by reports;
- `object_ref` with `api_version`, `kind`, `namespace`, and `name`;
- `evidence.field` and `evidence.predicate`;
- `container` for container-level rules.

Objects and findings are sorted by semantic identity. Reordering the same
documents therefore produces byte-equivalent finding JSON when serialized with
stable JSON settings.

The initial policy evaluates only facts present in the supplied manifest:

- Deployment, StatefulSet, DaemonSet, Job, CronJob, Ingress, NetworkPolicy and
  Secret presence/change signals;
- zero replicas or Job parallelism, suspended jobs, Recreate/OnDelete and a
  declared `maxUnavailable: 100%`;
- readiness/liveness probes per application container for long-running
  workloads, plus requests and limits for application and init containers;
- privileged containers, privilege escalation and host network/PID/IPC use;
- Service LoadBalancer, NodePort and non-empty `externalIPs`;
- PodDisruptionBudget `minAvailable: 0` or `maxUnavailable: 100%`.

The parser does not claim live drift, effective public reachability, workload
deletion, selector coverage, admission behavior or rollout impact that would
require cluster state.

## Secret privacy invariant

A Secret is reduced to `apiVersion`, `kind`, namespace and name before rule
evaluation. `data`, `stringData`, decoded values, full YAML and rejected input
fragments are never placed in public models, findings or exceptions. Callers
must apply the same discipline to their own file and process logging.

## Python API and migration

The structural API is:

```python
from preflightops import parse_kubernetes_manifests, scan_kubernetes

objects = parse_kubernetes_manifests(manifest_text)
findings = scan_kubernetes(manifest_text)
```

Earlier releases accepted incomplete snippets and inferred findings from global
case-insensitive keywords. That behavior remains available only through the
explicit compatibility adapter:

```python
from preflightops import scan_kubernetes_legacy

legacy_findings = scan_kubernetes_legacy("kind: Deployment")
```

Migrate by supplying complete objects, verifying field-level evidence against
representative fixtures and then replacing explicit legacy calls. Existing
finding ids, scores and severities are retained for equivalent structural
facts. New rules and evidence fields are additive. The legacy adapter remains
deprecated because comments, malformed YAML and fields from unrelated objects
can cause false conclusions.

## Rollback

For a controlled application rollback, pin the previous package version. A
Python-only consumer may temporarily select `scan_kubernetes_legacy` while its
manifests are corrected. Do not catch `KubernetesManifestError` and translate it
to PASS/LOW. There is no persisted parser state, schema migration or remote data
to reverse.

## Residual risks

- Kubernetes OpenAPI schemas and CRD-specific semantics are not validated.
- Live objects, admission policies, endpoints and combined NetworkPolicy or PDB
  behavior are outside the offline evidence boundary.
- Alias count limits bound references, but callers should retain stricter byte
  limits for untrusted multi-tenant inputs when appropriate.
- Policy coverage must evolve through versioned fixtures as supported kinds and
  Kubernetes semantics expand.
