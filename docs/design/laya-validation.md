# Laya integration validation — 22 September 2026

Local branch: `dev/jev-section`. Nothing was pushed or published.

## Automated checks

| Environment | Result |
|---|---|
| Python 3.10, Laya extra installed | 314 passed, 2 skipped |
| Python 3.11, Laya extra installed | 314 passed, 2 skipped |
| Python 3.12, Laya extra installed | 314 passed, 2 skipped |
| Python 3.13, Laya extra installed | 314 passed, 2 skipped |
| Ruff, bytecode compilation, whitespace and secret checks | Passed |
| Source distribution, wheel, metadata and artifact contents | Passed |
| Isolated base-wheel installation and CLI smoke test | Passed |

The two skipped tests require explicit live-provider opt-in. The optional SDK
parity test ran in all four environments. Base installs also passed the offline
suite without the Laya dependency; their SDK parity test is additionally skipped.

Tests cover mixed questions, provider selection, initialization reuse, concurrent
state isolation, token-boundary parity with the SDK, local asset integrity,
precision differences, explicit errors and protection failures. Default CI does
not download weights. A separate manually triggered compatibility workflow installs
the optional runtime and checks it without model downloads.

## Real local inference

All three bundled checkpoints were prepared from immutable Hugging Face revision
`1c5edc17a7acd8701df6fc341c0d179f1c62c982` of `convaiinnovations/laya`:

- English: passed two successive mixed Noul/Choice/Score batches on CPU.
- Multilingual: passed the same CPU smoke test.
- Typed-decisions: passed the same CPU smoke test.

Network connections were blocked during each smoke test, including model loading.
Prepared asset checksums remained unchanged after inference. These are functional
integration checks, not tests of multilingual accuracy or detection quality.

A separate real CLI run of `noul_prompt_override.nov` returned `0.9762`, matching
its illustrative threshold of `0.75`. That run reported about 104 seconds loading
and 695 milliseconds inference, on this macOS development machine during parallel
validation work. These observations are not a latency benchmark or service
guarantee. Subsequent scans in one detector reuse its model; separate CLI processes
load independently. Concurrent cold-start scans can exhaust their configured
queue wait; increase that allowance or initialize through a sequential SDK scan
before accepting concurrent traffic.

English and typed-decisions emitted an upstream warning about clamping the
`choice:11+` calibration bucket. NOVA records the adjustment warning; its current
DSL permits only 2–10 Choice options, so that bucket is outside supported rules.

## Dependencies and remaining limits

The tested runtime includes Laya 0.3.5, Transformers 5.10.4, Torch 2.14.0,
huggingface-hub 1.32.0, safetensors 0.8.0 and tokenizers 0.22.2. NumPy resolved to
2.2.6 on Python 3.10, 2.4.6 on 3.11 and 2.5.3 on 3.12/3.13. The Python 3.13
temporary environment's dependency audit reported no known vulnerabilities at
validation time. The Laya extra is also included in NOVA's declared-group audit.

CUDA selection and failure handling have offline tests, but no NVIDIA device was
available for actual CUDA inference. Linux/CUDA hardware compatibility and
deployment performance still require validation on the target host. MPS and
automatic checkpoint routing are not supported. In-process inference has no hard
cancellation deadline.

No OpenRouter requests were made for this implementation, and no model-quality
equivalence is claimed. The provider-comparison harness is available for an
explicitly requested evaluation on representative data.
