# API Contract

Status: active baseline contract from Batch 2

Version: 1.0

The authoritative provider-independent payload contracts are:

- `contracts/rag-request.schema.json`
- `contracts/rag-response.schema.json`

They define payloads, not a public HTTP route. Batch 3 may bind them to an internal CLI or endpoint, but must not
change their fields or state semantics without a recorded contract version and evaluation-set compatibility review.

## Request invariants

- Every request includes a portable request ID, question, explicit history, document scope and citation limit.
- `document_scope.mode=all` has no document IDs. `explicit` has at least one pseudonymous document ID.
- Retrieval and citations must stay inside an explicit scope.
- Conversation state used in evaluation is serialized in `history`; hidden server state is not comparable evidence.

## Response invariants

- `answered` requires a non-empty answer and at least one stable citation.
- `abstained` uses one of three exact non-factual messages, a supported reason and no citations.
- `error` represents runtime failure and never counts as abstention.
- Citations map an experiment chunk back to stable source blocks and a section/page locator without embedding raw text.

The OpenAI API and GCP-local stacks must emit the same schema. The offline schema registry at
`evaluation/schemas/registry.json` maps every external `$ref` to a checked-in local file; validators must not fetch a
schema from the network.
