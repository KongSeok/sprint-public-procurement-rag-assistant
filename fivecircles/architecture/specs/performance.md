# Performance

Status: active measurement contract from Batch 2.

The assignment does not define an absolute latency SLO. Record retrieval, generation and total latency for every
run; aggregate total p50/p95 and component p50 values. Latency remains a comparison metric until baseline evidence
supports a separately recorded SLO.

Every API run records token counts and non-negative USD cost. API evaluation cost coverage must be 100%, and the
total remains at or below USD 20. Every GCP-local run records GPU seconds and peak VRAM with the environment snapshot;
coverage must be 100%. The GCP stack may not exceed 4 vCPU, 16 GB RAM, one NVIDIA L4 and 100 GB disk.

`evaluation/config/metrics.json` is the frozen Batch 2 gate file. Missing, malformed or weakened gates fail scoring;
the file hash is stored separately from each stack's retrieval/generation configuration hash. A/B reports compare
only matching corpus, evaluation and scoring snapshots.
