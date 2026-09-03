# Local Stack Module Contract

- Owns deterministic local retrieval, pinned KURE embedding, Ollama model allowlists/digest,
  loopback vLLM generation, and official GCP run-record construction.
- Public imports are exposed through `midprojectrag.stacks.local`.
- Must not import OpenAI/Langfuse or write API stack artifacts.
- The local-first application composition lives in `local_application.py`, outside this
  module. It may reuse an existing OpenAI generation adapter under explicit payload/budget guards;
  this does not replace KURE/index/search or merge the standalone API evaluation branch.
- Network transport must disable proxies and redirects and accept literal loopback hosts only.
- The exact GCP profile is `nlpai-lab/KURE-v1` 1024-d + `Qwen/Qwen3-8B-AWQ`/vLLM AWQ;
  full model revisions are mandatory.
- Mac KURE + Ollama runs use `mac_local_equivalent`, remain non-official, and write prompts,
  answers, vectors, caches, and candidate records only under the configured private root.
- The logical 8,192-token generation guard uses the exact pinned Qwen tokenizer/chat template,
  the full transmitted system message, non-thinking mode, and the reserved 1,024 output tokens.
- Resumable candidates and score receipts are bound to config, evaluation, index-config, rows,
  vectors, and metadata hashes; preflight fails unless all cached models and the full index verify.
- Official `gcp_local` records require `us-central1`, 4 vCPU, 16 GB RAM, NVIDIA L4 telemetry,
  null API cost, and disk capacity no greater than 100 GB.
