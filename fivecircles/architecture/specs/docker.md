# Container and Runtime Notes

Docker is optional for the baseline and does not define product behavior.

- Local development may use a Python virtual environment.
- Scenario A must remain compatible with one GCP VM: 4 vCPU, 16 GB RAM, NVIDIA L4 and at most 100 GB disk.
- If containerization is added, pin CUDA/runtime/model revisions and mount restricted data read-only.
- Never bake source documents, model credentials, private evaluation files or vector stores into an image.
- Parser containers run without network and with per-file resource limits where practical.
