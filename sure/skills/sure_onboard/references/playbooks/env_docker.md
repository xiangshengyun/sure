# Docker Delivery Playbook

Every local `/sure_onboard` success is a registry-backed, digest-pinned container delivery. An upstream Dockerfile is input evidence, not a finished product: adapt it to the model wrapper, weights layout, server command, device requirements, and bounded fixture.

## Required flow

1. Write a model-specific Dockerfile and record its relative path and SHA-256.
2. Run `"$HARNESS_PYTHON_BIN" scripts/describe_harness_runtime.py`, add its exact `COPY --from=sure_harness_runtime` instruction to the Dockerfile, and pass its exact `--build-context` option to Docker. That option always names a digest-pinned Harness Runtime image; if the helper reports it has none, build one with `sure/runtime/harness/build_image.py` and export `SURE_HARNESS_RUNTIME_IMAGE=<repository>@sha256:<digest>` first.
3. Build one explicit target image tag.
4. Run Model Runtime import, load, inference, contract, and bounded-fixture checks inside that image. Start every `docker run` with an explicit `--entrypoint <interpreter>`: an image that carries its own ENTRYPOINT would otherwise run `<entrypoint> <your command>` (for example `python3 python3 validate.py`), which fails in a way that reads like a model defect rather than a command-line mistake.
5. Run Harness Runtime imports, dataset preparation, server orchestration, prediction, and prediction-validation checks through the image binding returned by the helper.
6. Record the sample output SHA-256 used by container validation.
7. Push that exact tag to the configured registry.
8. Resolve its registry digest and form `<repository>@sha256:<digest>`.
9. Pull and inspect that immutable reference.
10. Emit matching `docker_build_result.json`, `docker_validation.json`, and `docker_registry_result.json`.

The three documents must agree exactly on image tag, digest, immutable reference, Dockerfile hash, and sample hash. A passing boolean without those bindings is invalid.

## Runtime contract

The `docker_validation.json.model_runtime` object must declare both `working_dir` and a non-empty `server_command`. `working_dir` is the model bundle's absolute path inside the image; it may be `/model`, `/workspace/model`, or another explicit absolute path. The Dockerfile's `WORKDIR`, `SURE_MODEL_DIR`, `MODEL_DIR`, and model-root entries in `PYTHONPATH` must use the same path when they are written as literal values. Variable expressions such as `${MODEL_ROOT}` are deferred to the digest-pinned container smoke, which must prove the resolved path at runtime. Never fall back to `/workspace/model` when the model runtime did not declare its path.

Only the final build stage counts. `WORKDIR` and `ENV` set in an earlier stage describe the builder, not the image that ships, so declare the model paths in the last stage; a final stage that inherits a named stage inherits its values too. A relative `WORKDIR` resolves against the previous one. If that directory is not declared in the Dockerfile, the base image may supply it; the package gate checks the digest-pinned image's actual `Config.WorkingDir` instead of assuming `/`. Prefer an absolute `WORKDIR` in the final stage.

Every literal absolute path in `server_command` must be under `working_dir`, unless explicitly listed in `model_runtime.external_command_paths`. Use that list only for known image-owned executables/scripts or independently mounted inputs, for example `"external_command_paths": ["/usr/local/bin/python", "/opt/vendor/server.py"]`. Relative entries such as `server.py` run under `working_dir`. Never use the exception list to point a model-bundle entrypoint at a different mount root; the digest-pinned image check does not prove that a path belongs to the model bundle.

The validation run persists its results in the bundle's `artifacts/` directory, which is `<working_dir>/artifacts` in the container -- the only path the approval smoke mounts writable, and the only place it can read the stage evidence from. An image that bakes a results directory anywhere else (`ENV SURE_ARTIFACTS_DIR=/outputs`, for example) sends that evidence into the container's own layer, where it dies with the container: the run exits 0 and the approval gate sees a pass with no evidence behind it. Leave such a variable unset or point it at `<working_dir>/artifacts`; the package gate rejects any other absolute path.

`runtime_inventory.json` must expose:

- `execution_mode: container_only`;
- `container_runtime.working_dir` and `mount_policy.model_bundle.target` copied from the validated `model_runtime.working_dir`;
- the digest-pinned image reference;
- an explicit server command and MCP tool names;
- model/NFS inputs mounted read-only;
- a separate writable result workspace;
- host fallback disabled.
- `model_runtime.python_executable` and `harness_runtime.python_executable` are distinct;
- `harness_runtime.runtime_id` and `lock_sha256` equal the active common Harness Runtime;
- the Harness Runtime manifest and imports are live-probed in the exact digest image.

The Harness Runtime the image copies in carries a uv-managed CPython built against glibc and no longer bundles its libraries, so the image needs a glibc base (2.17 or newer) on a matching architecture; a musl/Alpine base cannot start it, and `check_container_package.verify_live_runtimes` fails the package when the interpreter does not run in the digest-pinned image.

The image must not depend on host absolute `.venv` paths. Model weights may be baked into the image or mounted from the approved model directory according to the declared policy, but the model mount stays read-only during Eval.

## Failure handling

- Docker daemon unavailable: keep the run partial/blocked; do not declare local success.
- Container checks differ from local checks: repair the Dockerfile or image dependencies and repeat the bounded container checks.
- Registry push or digest resolution fails: retry according to the normal retry policy; never substitute a mutable tag.
- Digest pull/inspect differs from the pushed image: fail packaging and investigate registry/tag mutation.
- GPU unavailable: apply the declared device policy and record the limitation; do not silently switch execution surfaces.
