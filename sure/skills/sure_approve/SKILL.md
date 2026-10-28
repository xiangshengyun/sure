---
name: sure-approve
description: Audit and explicitly approve a completed sure_onboard or sure_trans model bundle before publishing it for sure_infer.
---

# /sure_approve

Audit a completed `/sure_onboard` or `/sure_trans` bundle without mutating it, bind a human decision to the audited candidate, then publish it atomically for `/sure_infer`.

## Parameters

| Parameter | Required | Meaning |
| --- | --- | --- |
| `model_dir` | audit mode | Explicit readable producer bundle. Absolute paths and paths relative to the invocation directory are accepted. |
| `mode` | no | `audit` (default) or `approve`. |
| `repair` | no | `safe` (default) or `none`. Safe repair never changes executable behavior. |
| `review_manifest` | approve mode | `review_packet.json` emitted by a completed audit. |
| `decision` | approve mode | Explicitly `approve` or `reject`. The agent must never infer this value. |
| `replace` | no | Default `false`; an existing destination blocks publication. |
| `max_retries` | no | Gate retry limit; default 3. |

## Workflow

Run audit first:

```text
/sure_approve model_dir=/path/to/completed/model
```

The audit creates an isolated candidate under the run directory, verifies the producer contract and runtime, and ends with `review_packet.json` in `awaiting_approval`. It never writes to the approval root.

Read the review packet, make the decision yourself, then start a separate approval run:

```text
/sure_approve mode=approve review_manifest=/path/to/review_packet.json decision=approve
```

Approval verifies that the packet and candidate are unchanged. A positive decision publishes through a hidden same-filesystem sibling and atomic rename. A rejection records the decision and does not publish.

The publication root is always `storage.approved_models_roots[0]` from the active site policy. `/sure_infer` discovers approved model names below that same root, so the deployment configures it once and no command-level publication-root override exists.

## Boundaries

- Do not mutate the producer directory.
- Reject incomplete, failed, API-ready, and `docker-local` products.
- Accept Docker v1 only with a digest-pinned registry image. New producer bundles must carry
  `pull_verified=true`; during the temporary producer-contract migration, a legacy bundle may
  use `pull_verify.status=passed` with a matching `pull_verify.digest`, which is recorded as a
  warning and must be repaired by rerunning the producer.
- Accept Python v2 only with a sealed `uv` Model Runtime and site policy enabling local Python.
- Require passing original, adapter, MCP, and equivalence evidence for `/sure_trans`.
- Restrict safe repair to derived paths, publication permissions, and excluded caches. Never repair wrappers, configs, weights, payloads, locks, runtimes, images, provenance, or failed validation.
- Reject source/destination overlap, escaping links, special files, and destination collisions.
- Reject review packets whose destination does not match the active site's configured approved model root.
- Never create the human decision. Require the user-supplied `decision` parameter.

Read [producer-contracts.md](references/producer-contracts.md) when classifying the producer or diagnosing a failed audit. Read [repair-policy.md](references/repair-policy.md) before accepting or describing a repair.

## State Machine

Audit mode runs units 1-8; approve mode resumes from the prior packet and runs units 9-11.

| # | Unit | Product |
| --- | --- | --- |
| 1 | `resolve_input` | `approve_input_resolved.json` |
| 2 | `classify_producer` | `producer_contract_report.json` |
| 3 | `audit_integrity` | `integrity_report.json` |
| 4 | `plan_repairs` | `repair_plan.json` |
| 5 | `apply_repairs` | `repair_report.json` |
| 6 | `seal_candidate` | `approval_manifest.json` |
| 7 | `verify_runtime` | `runtime_verification.json` |
| 8 | `prepare_review` | `review_packet.json` |
| 9 | `verify_decision` | `approval_decision.json` |
| 10 | `publish` | `publication_result.json` |
| 11 | `verify_publication` | `approval_ready.json` |

Run only the current unit's script with Harness Python from this package. Each script accepts `--run-dir` and `--produces`; `resolve_approve_input.py` additionally receives invocation parameters. Do not call producer scripts to manufacture missing evidence.

If a gate produces a failed artifact, the run may finish with `status=failed` without reaching its terminal unit. The finish manifest must identify the blocked unit in `validation.failed_unit`, give a non-empty `validation.error`, and set `validation.published=false`. The hook requires the failed artifact to match the blocked gate's recorded content; it never accepts a failed gate as a successful review.

`verify_runtime` re-reads the sealed candidate's own `config.yaml` against the same rules the onboard gate applies: a declared `server.command` must name the framing it speaks (`protocol: mcp` or `jsonl`, never inferred from the channel) and must declare a `tools[]` entry a client can call, because the infer client filters the arguments it sends against `tools[].input_schema.properties`. A Python candidate's declared server is then started -- with the interpreter the deployment binding names, since the published bundle carries no `.venv` -- and the contract it advertises on `tools/list` must agree with the config. Refusing here costs a re-onboard; both defects otherwise surface first at inference, on an already-published bundle.

For a container candidate, `verify_runtime` also rejects model paths that disagree with the approved mount and starts its declared MCP or JSONL server under the digest-pinned image with the approved read-only model mount and a writable temporary output mount. The smoke uses the declared server environment, calls the declared tool, and checks the observation against the configured task. Arguments come from `artifacts/fixture_manifest.json`; a tool the fixture cannot drive must carry `artifacts/server_smoke_input.json` (`{"arguments": {...}}`) in the bundle. When neither can drive the tool the candidate is refused: the smoke never degrades to `--list-only` or `skipped`, because that would approve a model whose tool was never called. A tool whose schema requires no input is called with `{}`. The runtime receipt also records the image's resolved `WorkingDir`/`Env` and the environment the smoke server ran with, credentials redacted, so a later inference failure can be explained without rebuilding the image.

Container bundles created before the explicit runtime-path contract must be re-onboarded before reapproval. `docker_validation.json.model_runtime` must declare `working_dir` and `server_command`, and the inventory's working directory must match its model mount target. The existing `sure.onboard.docker_validation.v2` schema identifier alone does not establish compliance with these required fields; validation must inspect the document. This tightening is not backward compatible with older producer evidence. Reapproval verifies a newly sealed candidate; it does not rewrite existing published bundles.
