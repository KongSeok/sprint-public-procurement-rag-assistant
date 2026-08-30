# Local Stack Module Contract

- Owns deterministic local retrieval, Ollama model allowlists/digest and loopback transport.
- Public imports are exposed through `midprojectrag.stacks.local`.
- Must not import OpenAI/Langfuse or write API stack artifacts.
- Network transport must disable proxies and redirects and accept literal loopback hosts only.
