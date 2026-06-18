"""Sandboxed worker process for executing untrusted, model-generated code.

Runs as a separate Python process (NOT imported into the agent). The parent
(`SubprocessSandboxExecutor`) spawns it with a scrubbed environment, an empty
temp cwd, and resource limits, then talks to it over stdin/stdout using
length-prefixed JSON frames.

Lock-down order matters: we import the data libraries FIRST (while file access
is still allowed), then install a seccomp syscall filter, then run any
untrusted code. After lock-down the untrusted code cannot open sockets, exec
new programs, or (in strict mode) open new files.

Protocol (each frame = 4-byte big-endian length + UTF-8 JSON, except the
variables blob which is raw pickle):
  parent -> child:  {"rlimit_cpu":..,"rlimit_as":..,"rlimit_fsize":..,
                     "seccomp":bool,"strict":bool}        (config)
  parent -> child:  <pickle of {var_name: DataFrame}>     (length-prefixed)
  parent -> child:  {"cmd":"exec","code":"..."}  | {"cmd":"close"}
  child  -> parent: {"stdout":"..","error":null|"..",
                     "chart_data":<list|null>,"insight":<dict|null>}
"""

# Import order here is deliberate (data libs after stdlib, before lock-down);
# keep ruff's isort/E402 from "fixing" it.
# ruff: noqa: E402, I001

import contextlib
import io
import json
import pickle
import struct
import sys
import traceback

# Imported up front (before any lock-down) so the untrusted code never needs to
# open new files for these, and so they are available in its namespace.
import pandas as pd  # noqa: E402
import numpy as np  # noqa: E402

_IN = sys.stdin.buffer
_OUT = sys.stdout.buffer


def _read_exact(n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = _IN.read(n - len(buf))
        if not chunk:
            return buf
        buf += chunk
    return buf


def _read_frame() -> bytes | None:
    header = _read_exact(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack(">I", header)
    return _read_exact(length)


def _write_json(obj) -> None:
    data = json.dumps(obj, default=_json_default).encode("utf-8")
    _OUT.write(struct.pack(">I", len(data)))
    _OUT.write(data)
    _OUT.flush()


def _json_default(o):
    """Make numpy / pandas scalars JSON-serialisable."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return str(o)


def _apply_rlimits(cfg: dict) -> None:
    import resource

    def _set(which, value):
        if value:
            try:
                resource.setrlimit(which, (value, value))
            except (ValueError, OSError):
                pass

    _set(resource.RLIMIT_CPU, cfg.get("rlimit_cpu"))
    _set(resource.RLIMIT_AS, cfg.get("rlimit_as"))
    _set(resource.RLIMIT_FSIZE, cfg.get("rlimit_fsize"))


def _install_seccomp(strict: bool) -> bool:
    """Install a syscall filter. Returns True if applied, False if unavailable.

    Blocks network (socket/connect/...), program execution (execve), and new
    processes (fork). In strict mode also blocks opening new files. pandas/numpy
    compute on in-memory data needs none of these once imported.
    """
    try:
        import errno

        import pyseccomp as seccomp
    except Exception:
        return False

    deny = seccomp.ERRNO(errno.EACCES)
    flt = seccomp.SyscallFilter(defaction=seccomp.ALLOW)
    blocked = [
        "socket",
        "socketpair",
        "connect",
        "bind",
        "listen",
        "accept",
        "accept4",
        "sendto",
        "sendmsg",
        "recvfrom",
        "recvmsg",
        "execve",
        "execveat",
        "fork",
        "vfork",
        "ptrace",
        "process_vm_readv",
        "process_vm_writev",
    ]
    if strict:
        blocked += ["open", "openat", "openat2", "creat"]
    for name in blocked:
        try:
            flt.add_rule(deny, name)
        except (ValueError, OSError):
            # syscall not known on this arch/kernel — skip
            pass
    flt.load()
    return True


def _extract_results(ns: dict):
    chart = ns.get("chart_data")
    if isinstance(chart, pd.DataFrame):
        chart = chart.to_dict("records")
    if not isinstance(chart, list):
        chart = None

    insight = ns.get("insight")
    if isinstance(insight, (bytes, bytearray)):
        try:
            insight = json.loads(insight.decode("utf-8"))
        except Exception:
            insight = None
    elif isinstance(insight, str):
        try:
            insight = json.loads(insight)
        except Exception:
            insight = None
    elif not isinstance(insight, dict):
        insight = None
    return chart, insight


def _run_block(code: str, ns: dict):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(code, "<cell>", "exec"), ns)
        error = None
    except Exception:
        error = traceback.format_exc(limit=4)
    chart, insight = _extract_results(ns)
    return buf.getvalue(), error, chart, insight


def main() -> None:
    config = json.loads(_read_frame() or b"{}")
    _apply_rlimits(config)

    variables = pickle.loads(_read_frame() or b"")
    namespace: dict = {"__name__": "__main__", "pd": pd, "np": np}
    namespace.update(variables)

    seccomp_active = False
    if config.get("seccomp", True):
        seccomp_active = _install_seccomp(strict=config.get("strict", False))

    # Signal readiness (and whether the syscall filter is really in force) only
    # after lock-down, so the parent knows the sandbox state before sending code.
    _write_json({"ready": True, "seccomp_active": seccomp_active})

    while True:
        frame = _read_frame()
        if frame is None:
            break
        message = json.loads(frame)
        if message.get("cmd") == "exec":
            stdout, error, chart, insight = _run_block(
                message.get("code", ""), namespace
            )
            _write_json(
                {
                    "stdout": stdout,
                    "error": error,
                    "chart_data": chart,
                    "insight": insight,
                }
            )
        else:  # "close" or anything unexpected
            break


if __name__ == "__main__":
    main()
