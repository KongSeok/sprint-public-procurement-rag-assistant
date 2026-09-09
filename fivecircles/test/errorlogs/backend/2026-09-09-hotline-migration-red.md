# HOTLINE.2 expected TDD RED

- Recorded at: 2026-09-09T11:48:48+09:00; the expected RED occurred earlier in this session, before module creation.
- Context: `.venv/bin/python -m unittest -q tests.test_hotline_runtime`, PYTHONPATH=src.
- Observed: unittest collected one failed module import; `ImportError: cannot import name hotline from midprojectrag`, exit1.
- Cause: expected RED for the new module, not missing environment dependencies.
- Resolution: extracted the existing hotline into the new module and linked the compatibility launcher. Focused30 + shared64 passed afterward.
- Prevention: distinguish missing implementation from dependency failures; do not reinstall packages for an expected RED.
