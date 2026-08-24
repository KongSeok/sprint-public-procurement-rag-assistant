---
name: find-proposal
description: Quickly find and read proposal documents by number (14-17) or keyword. Use when user mentions "문서 X" or references a specific proposal.
---

# Find Proposal

This skill helps quickly locate and read proposal documents in the ontology layer proposals folder.

## When to Use

- User mentions "문서 14", "문서 17", etc.
- User references export, input, data modules
- Need to find specific architectural proposals

## Document Index

### Data Pipeline (14-17)
- **14**: `14-input-data.md` - Input data spec (legacy)
- **15**: `15-input-data2.md` - Input data spec v2 (active)
- **16**: `16-data-input-module.md` - CandidateBuilder + TripleExtractor
- **17**: `17-export-module.md` - ExportWorker (APPROVED → event promotion)

### Architecture (ex00-13)
- **ex00**: Overview
- **ex01**: Basic concepts
- **ex02**: Basic 4 entities
- **ex03**: Quick 20 Questions
- **ex04**: Triple store
- **ex05**: Level 4 ontology
- **ex06**: L1-3 query examples
- **ex07**: Migration steps
- **ex08**: Time/episode/chronicle
- **ex09**: RDB or RDF
- **ex10**: Versions 2-4
- **ex11**: Reveals
- **ex12**: Predicate standardization
- **ex13**: Standard predicates

### Version Plans
- **v2.5-def-plan.md**: V2.5 definition plan
- **v3-details-debate.md**: V3 details debate

## Usage

```bash
# Find document by number
find proposals/공유-온톨로지레이어구축 -name "17-*.md"

# Quick read
cat fivecircles/architecture/proposals/공유-온톨로지레이어구축/17-export-module.md
```

## Protocol

1. When user mentions "문서 N", immediately check this index
2. Read the corresponding file from proposals folder
3. If not in index, search the proposals directory
4. Never wander to queue.json or other files first
