# API Stack Module Contract

- Owns OpenAI model allowlists, tokenizer assets, pricing, SDK clients and API egress gates.
- Public imports are exposed through `midprojectrag.stacks.api`.
- Must not import `midprojectrag.stacks.local` or write local stack artifacts.
- External calls require the existing explicit corpus egress approval and budget ledger.
