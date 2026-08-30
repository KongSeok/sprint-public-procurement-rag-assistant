# Visual adapter environment flags did not enforce offline execution

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the first checksum-pinned OCR/caption adapter contract could launch an arbitrary local process
  with socket access while metadata claimed zero external calls and no private egress.

## Symptom

The adapter set offline model environment flags and `NO_PROXY`, but no operating-system policy prevented
the subprocess from opening a direct socket. A correct checksum proves executable identity, not network
isolation.

## Root cause

The implementation treated cooperative environment variables as an enforcement boundary. They disable
well-behaved model download clients but cannot constrain arbitrary code in the pinned wrapper or its child
processes.

## Resolution

- Replaced the v1 command identity with a v2 identity that requires a checksum-pinned, allowlisted OS
  sandbox: macOS `sandbox-exec` or Linux `bwrap --unshare-net`.
- Wrapped every OCR/caption subprocess in a fixed deny-network profile and fail closed when the backend,
  platform, path, or checksum does not match.
- Kept model downloads forbidden and retained bounded stdin/stdout/stderr, timeout, and pre/post pin checks.

## Verification

- Focused understanding/runner/CLI tests passed with the new required sandbox contract.
- A local macOS probe inside the fixed profile returned `EPERM` for a loopback socket attempt.
- No private crop, OCR text, path, filename, model output, or credential was used in the probe or this log.

## Prevention

- Never equate `*_OFFLINE`, proxy variables, or an executable checksum with egress prevention.
- Assert `private_egress=false` only for fixture adapters or adapters launched inside a verified OS network
  sandbox.
- Re-pin the sandbox binary after operating-system updates and refuse silent backend fallback.
