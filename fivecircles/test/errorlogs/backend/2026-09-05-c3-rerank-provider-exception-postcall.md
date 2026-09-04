Timestamp: 2026-09-05 05:26
Context: EH2.6.c3.2 reranker execution

Issues
1) Provider exception path skipped post-call dependency validation and could mint an immediately invalid provider_error receipt.

Resolution
- Unified normal and exceptional returns behind the same post-call gate; drift now becomes sanitized consumed contract_error.

Prevention
- Every attempted external callable must revalidate exact source/store/config/runtime/component before parsing or minting.
