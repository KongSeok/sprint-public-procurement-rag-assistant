# MidProjectRAG System Overview

## Pipeline

1. Private corpus snapshot materialization
2. Metadata normalization and 100/100 manifest join
3. HWP/PDF structural extraction into stable source blocks
4. Experiment-specific chunking and embedding
5. Metadata routing plus Dense retrieval baseline
6. Context-bounded generation with citations or abstention
7. Contract validation, evaluation and A/B reporting

## Shared Core and Provider Adapters

The ingestion, chunking, retrieval, citation, request/response and evaluation layers are shared.
Only model/provider adapters differ:

- `api`: OpenAI embedding and generation within the course budget
- `gcp_local`: Hugging Face embedding and generation on the course L4 VM

Both adapters implement the same contracts and emit the same private run-record schema.

## Baseline Boundary

The first runnable product is a CLI or thin service using simple chunks, Dense top-k retrieval and a single generator.
UI polish, MMR, hybrid, multi-query and reranking are not baseline dependencies.
