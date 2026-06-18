"""Sandboxed code executor: runs model-generated code in a locked-down subprocess.

Same CodeAct loop as ``LocalCodeExecutor`` (it subclasses it), but each code
block runs in a separate Python process started by ``_sandbox_worker`` with:

- a **scrubbed environment** (no API keys / DB creds / AWS creds in the process),
- an **empty temp cwd**,
- **resource limits** (CPU time, file size) via ``setrlimit``, and
- a **seccomp syscall filter** (Linux) blocking network, ``execve`` and ``fork``;
  strict mode also blocks opening new files.

No Docker or external services required. seccomp needs ``pyseccomp`` on Linux;
where it is unavailable the process still benefits from env-scrubbing + rlimits
(network is then NOT blocked, so only use that for trusted input).
"""

import asyncio
import contextlib
import json
import os
import pickle
import shutil
import signal
import struct
import sys
import tempfile
from typing import Dict, Optional, Tuple

import pandas as pd

from src.agent.config import AgentSettings
from src.agent.subagents.analyst.code_executors.local_executor import (
    LocalCodeExecutor,
    _Runner,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_WORKER = os.path.join(os.path.dirname(__file__), "_sandbox_worker.py")

# Resource limits for the worker process.
RLIMIT_CPU_SECONDS = 30  # CPU-time (SIGXCPU/kill) — the main DoS guard
RLIMIT_FSIZE_BYTES = 64 * 1024 * 1024  # max bytes any write can produce

# Environment passed to the worker: NO secrets. Thread caps keep BLAS from
# spawning pools (so the CPU limit is meaningful and memory stays bounded).
_WORKER_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "LC_ALL": "C.UTF-8",
}


class SubprocessSandboxExecutor(LocalCodeExecutor):
    """Code executor that runs each block in a sandboxed subprocess."""

    def _make_runner(self) -> _Runner:
        return _SubprocessRunner(
            timeout_seconds=self.EXECUTION_TIMEOUT,
            seccomp=AgentSettings.sandbox_seccomp,
            strict=AgentSettings.sandbox_strict,
        )


class _SandboxSession:
    """Owns the worker subprocess and the length-prefixed framing protocol."""

    def __init__(self, seccomp: bool, strict: bool):
        self._seccomp = seccomp
        self.strict = strict
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._tmpdir: Optional[str] = None
        self.seccomp_active = False

    async def start(self, variables: Dict[str, pd.DataFrame]) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="zeno-sandbox-")
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            _WORKER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self._tmpdir,
            env=_WORKER_ENV,
            close_fds=True,
            start_new_session=True,  # own process group, for clean kill
            preexec_fn=_set_rlimits,  # runs in the child before exec
        )
        config = {
            "rlimit_cpu": RLIMIT_CPU_SECONDS,
            "rlimit_fsize": RLIMIT_FSIZE_BYTES,
            "seccomp": self._seccomp,
            "strict": self.strict,
        }
        await self._send(json.dumps(config).encode("utf-8"))
        await self._send(pickle.dumps(variables, protocol=4))

        # Wait for the worker to finish importing libs + locking down.
        ready = await asyncio.wait_for(self._recv(), timeout=60)
        info = json.loads(ready) if ready else {}
        self.seccomp_active = bool(info.get("seccomp_active"))

    async def _send(self, payload: bytes) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(struct.pack(">I", len(payload)))
        self._proc.stdin.write(payload)
        await self._proc.stdin.drain()

    async def _recv(self) -> Optional[bytes]:
        assert self._proc and self._proc.stdout
        try:
            header = await self._proc.stdout.readexactly(4)
        except asyncio.IncompleteReadError:
            return None
        (length,) = struct.unpack(">I", header)
        try:
            return await self._proc.stdout.readexactly(length)
        except asyncio.IncompleteReadError:
            return None

    async def exec_block(self, code: str, timeout: float) -> dict:
        """Send a code block; return the worker's response dict.

        Raises on timeout or a dead worker so the caller can surface an error.
        """
        await self._send(json.dumps({"cmd": "exec", "code": code}).encode())
        frame = await asyncio.wait_for(self._recv(), timeout=timeout)
        if frame is None:
            raise RuntimeError("sandbox worker exited unexpectedly")
        return json.loads(frame)

    async def close(self) -> None:
        proc = self._proc
        if proc is not None:
            _kill_process_group(proc)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=5)
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


class _SubprocessRunner(_Runner):
    """Runner that executes each block in a ``_SandboxSession``."""

    def __init__(self, timeout_seconds: int, seccomp: bool, strict: bool):
        self._timeout = timeout_seconds
        self._session = _SandboxSession(seccomp=seccomp, strict=strict)

    async def start(self, prepared: Dict[str, pd.DataFrame]) -> None:
        await self._session.start(prepared)
        logger.info(
            "Sandbox session started (seccomp=%s, strict=%s)",
            self._session.seccomp_active,
            self._session.strict,
        )

    async def run_block(self, code: str) -> Tuple[str, object, object]:
        try:
            resp = await self._session.exec_block(code, timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("Sandbox block timed out after %ss", self._timeout)
            return (
                f"Error: execution timed out after {self._timeout}s",
                None,
                None,
            )
        except Exception as e:
            logger.warning(f"Sandbox execution error: {e}")
            return (f"Error: {e}", None, None)

        output = resp.get("stdout") or ""
        if resp.get("error"):
            output = (output + "\n" + resp["error"]).strip()
        return output, resp.get("chart_data"), resp.get("insight")

    async def close(self) -> None:
        await self._session.close()


def _set_rlimits() -> None:  # pragma: no cover - runs in the child process
    """Applied in the child before exec (preexec_fn). Belt-and-braces with the
    limits the worker also sets from the config frame."""
    import resource

    for which, value in (
        (resource.RLIMIT_CPU, RLIMIT_CPU_SECONDS),
        (resource.RLIMIT_FSIZE, RLIMIT_FSIZE_BYTES),
    ):
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):
            pass


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
