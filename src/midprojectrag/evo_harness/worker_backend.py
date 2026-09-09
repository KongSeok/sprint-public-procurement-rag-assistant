"""Parent-side Backend proxy for one persistent local MLX Qwen process."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from .policy import Completion, ModelIdentity
from .state import HarnessError


class PersistentMLXBackend:
    def __init__(self, *, python: Path | None = None, model_dir: Path | None = None,
                 model_manifest: Path | None = None, expected_revision: str | None = None,
                 startup_timeout: float = 30.0, command: list[str] | None = None,
                 network_sandbox: bool = True, stderr_path: Path | None = None):
        if command is None:
            if not all((python, model_dir, model_manifest, expected_revision)):
                raise ValueError("worker_runtime_args_required")
            command = [str(Path(python).absolute()), "-m", "midprojectrag.evo_harness.mlx_worker",
                       "--model-dir", str(Path(model_dir).resolve()),
                       "--model-manifest", str(Path(model_manifest).resolve()),
                       "--expected-revision", str(expected_revision)]
            if network_sandbox and sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
                command = ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)", *command]
        env = dict(os.environ)
        src_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = src_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false",
                   PYTHONDONTWRITEBYTECODE="1")
        self._stderr_handle = None
        stderr = subprocess.DEVNULL
        if stderr_path is not None:
            target = Path(stderr_path)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._stderr_handle = target.open("a", encoding="utf-8")
            os.chmod(target, 0o600)
            stderr = self._stderr_handle
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=stderr, text=True, bufsize=1, env=env,
                                        start_new_session=True)
        self._next_id = 1
        try:
            ready = self._read_line(startup_timeout)
            if (ready.get("op") != "ready" or type(ready.get("identity")) is not dict
                    or type(ready.get("load_seconds")) not in (int, float)):
                raise HarnessError("worker_ready_invalid")
            self.identity = ModelIdentity(**ready["identity"])
            self.load_seconds = float(ready["load_seconds"])
            self.manifest_sha256 = ready.get("manifest_sha256")
        except Exception:
            self._terminate()
            raise

    def _read_line(self, timeout: float) -> dict:
        if type(timeout) not in (int, float) or timeout <= 0:
            raise TimeoutError("worker_deadline")
        if self.process.stdout is None:
            raise HarnessError("worker_stdout_missing")
        ready, _, _ = select.select([self.process.stdout.fileno()], [], [], float(timeout))
        if not ready:
            raise TimeoutError("worker_deadline")
        line = self.process.stdout.readline()
        if not line:
            raise HarnessError("worker_terminated")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarnessError("worker_protocol_invalid") from exc
        if type(value) is not dict:
            raise HarnessError("worker_protocol_invalid")
        return value

    def _exchange(self, payload: dict, timeout: float) -> dict:
        if self.process.poll() is not None:
            raise HarnessError("worker_terminated")
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, **deepcopy(payload)}
        try:
            if self.process.stdin is None:
                raise HarnessError("worker_stdin_missing")
            self.process.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
            self.process.stdin.flush()
            response = self._read_line(timeout)
        except TimeoutError:
            raise
        except (BrokenPipeError, OSError) as exc:
            raise HarnessError("worker_terminated") from exc
        if response.get("id") != request_id:
            raise HarnessError("worker_response_id_mismatch")
        if response.get("ok") is not True:
            code = response.get("code")
            if type(code) is not str or not code or len(code) > 128:
                code = "worker_error"
            raise HarnessError(code)
        return response

    @property
    def alive(self) -> bool:
        process = getattr(self, "process", None)
        return process is not None and process.poll() is None

    def count_messages(self, messages: list[dict]) -> int:
        try:
            response = self._exchange({"op": "count", "messages": messages}, 30.0)
        except TimeoutError:
            self._terminate()
            raise
        count = response.get("count")
        if type(count) is not int or count < 1:
            raise HarnessError("exact_token_count_required")
        return count

    def complete(self, messages: list[dict], *, max_tokens: int, timeout: float,
                 json_schema: dict | None = None) -> Completion:
        try:
            response = self._exchange({"op": "complete", "messages": messages, "max_tokens": max_tokens,
                                       "timeout": float(timeout), "json_schema": json_schema},
                                      max(1.0, float(timeout) + 1.0))
        except TimeoutError:
            self._terminate()
            raise
        value = response.get("completion")
        if type(value) is not dict:
            raise HarnessError("worker_completion_invalid")
        try:
            return Completion(**value)
        except TypeError as exc:
            raise HarnessError("worker_completion_invalid") from exc

    def _close_pipes(self) -> None:
        process = getattr(self, "process", None)
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def _terminate(self) -> None:
        process = getattr(self, "process", None)
        if process is None:
            return
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except Exception:
                    pass
                try:
                    process.wait(timeout=1.0)
                except Exception:
                    pass
        self._close_pipes()

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                try:
                    self._exchange({"op": "shutdown"}, 2.0)
                    self.process.wait(timeout=2.0)
                    self._close_pipes()
                except Exception:
                    self._terminate()
            else:
                self._close_pipes()
        finally:
            if self._stderr_handle is not None:
                self._stderr_handle.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
