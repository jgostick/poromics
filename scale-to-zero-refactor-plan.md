Read memory [](file:///Users/jeffgostick/Library/Application%20Support/Code/User/workspaceStorage/73314fc986ebc210941ac76f49da202d/GitHub.copilot-chat/memory-tool/memories/ZTgwZGM4ZmMtM2YxMS00NzFmLThhZTItYjdhMTNjNjcxM2Fj/plan.md)

## Plan: RunPod Serverless Python Remote

Replace the stateful custom Python remote HTTP job server with RunPod queue-based serverless execution for CPU remote analyses, while introducing a shared remote-operation registry so future analyses add a subclass or module instead of editing python_remote_server.py. Keep queue structure in YAML and deploy-specific endpoint and auth values in env, and switch serverless requests away from inline NumPy payloads toward storage references because RunPod async requests cap payloads at 10 MB.

**Steps**
1. Phase 1: Define the shared remote-operation contract. Introduce a Django-free RemotePythonOperation base abstraction for remote-capable analyses, with stable analysis_type identifiers, input and output schema hooks, storage-reference helpers, local execution, and remote result normalization. Extract the duplicated pore-size and network-extraction compute logic out of python_remote_server.py and existing analysis wrappers into this shared operation layer so both Django and the remote worker execute the same logic.
2. Phase 1: Add built-in discovery and registration for operations. Depends on 1. Replace the current hardcoded builtin handler registration with an operation registry that discovers built-in operation modules automatically and still supports optional external plugin modules via environment configuration. After this one-time refactor, adding a new Python remote analysis should only require adding a new operation module or subclass and its tests, not editing python_remote_server.py.
3. Phase 2: Split runtime adapters from analysis registration. Depends on 1 and 2. Refactor python_remote_server.py into a thin bootstrap that loads the shared operation registry and supports two runtime adapters: legacy HTTP /job mode for local development and backward compatibility, and RunPod serverless handler mode for production scale-to-zero execution. Keep taichi and julia out of scope.
4. Phase 2: Introduce a caller-side transport abstraction. Depends on 1; parallel with 3 after the contract is fixed. Refactor python_remote_client.py into transport implementations for legacy HTTP and RunPod queue-based endpoints. Add explicit queue-level transport metadata to queues.yaml and parser support in queue_catalog.py so Python remote queues declare protocol and runtime without hardcoding deploy URLs.
5. Phase 2: Extend settings for serverless transport. Depends on 4. Extend settings.py to parse RunPod endpoint, auth, and policy settings, including endpoint base URL or endpoint ID, API key, default execution timeout, TTL, poll backoff defaults, and cold-start grace settings. Keep deploy-specific values in env vars; keep non-deploy-specific routing and transport metadata in queues.yaml.
6. Phase 3: Replace inline NumPy transport with storage-backed references for serverless. Depends on 1, 4, and 5. Stop sending base64-encoded arrays to serverless endpoints. Build payloads around an image reference that the worker can fetch directly from storage, using public media URLs when available and presigned GET URLs otherwise. Preserve inline base64 payloads only for legacy or local HTTP mode and tests.
7. Phase 3: Add artifact-backed output handling for large results. Depends on 6. Introduce large-result handling for serverless operations, especially network extraction, so the worker can upload a pickle or serialized artifact via a presigned PUT URL or shared storage path and return only compact metadata plus artifact location. Keep small outputs like pore-size inline.
8. Phase 4: Rewire task orchestration around durable remote job metadata. Depends on 4, 5, 6, and 7. Update tasks.py so CPU remote jobs submit through a shared dispatcher, persist remote_transport, remote_endpoint, remote_job_id, and artifact metadata into AnalysisJob.parameters, and resume polling on Celery retry instead of resubmitting duplicate remote jobs. Move bespoke submit and poll loops out of individual analysis modules into shared execution helpers so pore-size and network extraction use the same backoff, timeout, cancel, and error-mapping behavior.
9. Phase 4: Change launch-path readiness semantics for scale-to-zero. Depends on 4 and 5. Update image_analysis.py so serverless Python queues no longer hard-fail on _server_healthy() during launch. A cold endpoint with zero running workers is normal in a scale-to-zero model, so form submission should validate broker and queue config and let the Celery worker own remote submission. Recommendation: keep RunPod API credentials only on services that truly need to submit or inspect serverless jobs.
10. Phase 5: Update deployment, documentation, and rollout guidance. Depends on 3, 5, and 9. Update render.yaml and the remote Python docs to describe the new RunPod queue-based serverless configuration, the new extension workflow for operation subclasses, the payload-size constraint, and the storage-reference and artifact strategy. Document the new routing and transport rules in compute-routing.md and roll out poresize-runpod before extraction-runpod.
11. Phase 5: Expand automated verification. Depends on all prior steps. Add tests for operation discovery, RunPod transport request, status, and cancel flows, auth and backoff behavior, storage-reference payload generation, artifact-backed outputs, retry and resume with persisted remote_job_id, and the relaxed launch-path behavior for cold serverless queues.

**Relevant files**
- python_remote_server.py — convert from a stateful builtin-handler server into a thin runtime bootstrap with registry-driven HTTP and RunPod modes.
- python_remote_client.py — split into transport logic, RunPod /run plus /status/{job_id} client behavior, auth, backoff, cancel, and payload and reference helpers.
- tasks.py — centralize remote submission and polling and persist remote job metadata for retry-safe execution.
- image_analysis.py — remove blocking health gating for serverless queues while preserving routing metadata.
- pore_size_distribution.py — stop owning bespoke remote transport logic; keep local compute behavior wired through the shared operation contract.
- network_extraction.py — same refactor, plus artifact-backed output handling.
- queue_catalog.py — add optional transport and runtime metadata parsing for queues.
- settings.py — parse RunPod transport, auth, and policy env vars.
- queues.yaml — mark only Python remote queues with explicit serverless transport metadata while keeping deploy-specific endpoints in env.
- render.yaml — wire new serverless env vars for the services that need them.
- remote-python-analyses.md — update deployment and analysis-extension guidance.
- compute-routing.md — document the new serverless routing behavior and constraints.
- test_python_remote_server_plugins.py — repoint plugin tests at operation discovery.
- test_poresize_remote.py — cover serverless dispatch and storage-reference inputs.
- test_network_extraction_remote.py — cover artifact-backed outputs and retry and resume behavior.

**Verification**
1. Unit-test the new registry so a new operation module becomes executable without touching python_remote_server.py.
2. Unit-test the RunPod transport against mocked /run, /status/{job_id}, /cancel/{job_id}, and auth and error responses, including cold-start retries and 429 backoff.
3. Unit-test storage-reference payload builders for both public-media URLs and signed or fallback cases, plus large-output artifact upload reference generation.
4. Verify run_poresize_job can submit, persist remote_job_id, survive one retry, resume polling, and complete without duplicating the remote job.
5. Verify run_network_extraction_job returns summary metadata plus a stored artifact path without exceeding result-size limits.
6. Verify launch pages still queue jobs successfully when the serverless endpoint is cold and /health would report zero running workers.
7. Run the targeted Django tests for the Python remote path after refactor.
8. Do a staged manual smoke test by converting poresize-runpod first, then extraction-runpod, validating cold-start behavior, final stored results, and Celery-to-RunPod job correlation.

**Decisions**
- Use RunPod queue-based serverless endpoints, not load-balancer or custom HTTP endpoints, because their native /run plus /status lifecycle matches the existing async job model and enables scale-to-zero.
- Serialize operation descriptors and data references, not executable Python class objects or code.
- Keep queue topology in queues.yaml, but keep deploy-specific endpoint addresses, IDs, and secrets in environment variables.
- Treat RunPod’s 10 MB async payload limit and result-retention limits as design constraints; use storage references for inputs and artifact-backed outputs where needed.
- Keep legacy HTTP mode available temporarily for local development and rollback, but make RunPod serverless the production path for Python remote queues.
- Explicitly exclude taichi and julia changes from this plan.



## Execution Checklist

Inserted into memory file [](file:///Users/jeffgostick/Library/Application%20Support/Code/User/workspaceStorage/73314fc986ebc210941ac76f49da202d/GitHub.copilot-chat/memory-tool/memories/ZTgwZGM4ZmMtM2YxMS00NzFmLThhZTItYjdhMTNjNjcxM2Fj/plan.md)

1. Extract a shared RemotePythonOperation base and move pore-size plus network-extraction compute logic into registry-loaded operation modules.
2. Replace hardcoded builtin handler registration in python_remote_server.py with automatic operation discovery, while keeping optional plugin-module loading.
3. Split python_remote_server.py into a thin bootstrap with legacy HTTP mode and RunPod serverless handler mode.
4. Refactor python_remote_client.py into transport adapters for legacy HTTP and RunPod queue-based endpoints.
5. Extend queues.yaml, queue_catalog.py, and settings.py so Python remote queues declare transport type while RunPod endpoint IDs, auth, and timeout policy stay in env.
6. Replace inline NumPy payloads for serverless with storage-backed image references, using public media URLs or presigned GET URLs.
7. Add artifact-backed output handling for large serverless results, especially network extraction.
8. Centralize CPU remote submit, poll, cancel, retry, and error mapping in tasks.py, and persist remote_job_id plus transport metadata so retries resume instead of resubmitting.
9. Remove launch-time hard failure on Python remote health checks for serverless queues in image_analysis.py.
10. Update render.yaml and the remote-compute docs, then roll out poresize-runpod first and extraction-runpod second.
11. Verify with focused registry, transport, storage-reference, retry-resume, and cold-start queue tests before doing staged manual smoke tests.
