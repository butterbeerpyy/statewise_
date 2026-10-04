from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import threading
import re
import socket
import time
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = "statewise-experiment-manager-v1"
_SECRET_KEY = re.compile(r"(?:api[_-]?key|secret|password|access[_-]?token|authorization)", re.I)
_SECRET_VALUE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_secrets(value: Any, key: str = "") -> Any:

    if _SECRET_KEY.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return _SECRET_VALUE.sub("<redacted>", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        redact_secrets(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_WRITE_LOCKS: dict[str, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _write_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _WRITE_LOCKS[key] = lock
        return lock


def write_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


    temporary = path.parent / f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"


    with _write_lock(path):
        temporary.write_text(
            json.dumps(redact_secrets(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.replace(temporary, path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


class EpisodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class FailureKind(str, Enum):
    API_AUTH = "api.auth"
    API_RATE_LIMIT = "api.rate_limit"
    API_TIMEOUT = "api.timeout"
    API_CONNECTION = "api.connection"
    API_SERVER = "api.server"
    API_REQUEST = "api.request"
    MODEL_RESPONSE_CONTRACT = "model.response_contract"
    WORKSPACE_SETUP = "workspace.setup"
    WORKSPACE_POLICY = "workspace.policy"
    EPISODE_RUNTIME = "episode.runtime"
    ORACLE = "measurement.oracle"
    EVALUATOR = "measurement.evaluator"
    INTERRUPTED = "process.interrupted"
    UNKNOWN = "unknown"


DEFAULT_RETRYABLE_FAILURES = frozenset({
    FailureKind.API_RATE_LIMIT,
    FailureKind.API_TIMEOUT,
    FailureKind.API_CONNECTION,
    FailureKind.API_SERVER,


    FailureKind.API_REQUEST,


    FailureKind.MODEL_RESPONSE_CONTRACT,
    FailureKind.INTERRUPTED,
})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    initial_backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0
    retryable_failures: frozenset[FailureKind] = DEFAULT_RETRYABLE_FAILURES

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if min(
            self.initial_backoff_seconds,
            self.backoff_multiplier,
            self.max_backoff_seconds,
        ) < 0:
            raise ValueError("retry backoff values must be non-negative")

    def delay(self, completed_attempts: int) -> float:
        if completed_attempts <= 0:
            return 0.0
        delay = self.initial_backoff_seconds * (
            self.backoff_multiplier ** max(0, completed_attempts - 1)
        )
        return min(delay, self.max_backoff_seconds)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["retryable_failures"] = sorted(item.value for item in self.retryable_failures)
        return data


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: str
    case_id: str
    condition: str
    trial: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.episode_id.strip():
            raise ValueError("episode_id must be non-empty")
        if self.trial < 0:
            raise ValueError("trial must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return redact_secrets(asdict(self))


@dataclass(frozen=True)
class AttemptContext:
    run_id: str
    attempt: int
    workspace: Path
    provider_profile: str | None = None


class ExperimentFailure(RuntimeError):


    def __init__(
        self,
        kind: FailureKind,
        message: str,
        *,
        retryable: bool | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.details = dict(details or {})


def classify_exception(exc: Exception) -> FailureKind:

    name = type(exc).__name__.lower()
    message = str(exc).lower()
    combined = f"{name} {message}"
    if any(token in combined for token in ("authentication", "unauthorized", "invalid api key")):
        return FailureKind.API_AUTH
    if "permissiondenied" in name or "forbidden" in message:
        return FailureKind.API_AUTH
    if "ratelimit" in name or "rate limit" in message or "status code: 429" in message:
        return FailureKind.API_RATE_LIMIT
    if "timeout" in combined or "timed out" in combined:
        return FailureKind.API_TIMEOUT
    if any(token in combined for token in ("apiconnection", "connectionerror", "connection reset", "dns")):
        return FailureKind.API_CONNECTION
    if any(token in combined for token in ("internalserver", "service unavailable", "bad gateway", "status code: 5")):
        return FailureKind.API_SERVER
    if any(token in name for token in ("badrequest", "unprocessableentity")):
        return FailureKind.API_REQUEST
    if any(token in combined for token in ("jsondecode", "unbalanced json", "no json object", "response contract")):
        return FailureKind.MODEL_RESPONSE_CONTRACT
    if "runtimepolicy" in name or "escapes workspace" in message:
        return FailureKind.WORKSPACE_POLICY
    if any(token in combined for token in ("workspace", "temporarydirectory", "filenotfound", "permissionerror")):
        return FailureKind.WORKSPACE_SETUP
    if "oracle" in combined:
        return FailureKind.ORACLE
    if any(token in combined for token in ("evaluator", "grading", "taxonomy")):
        return FailureKind.EVALUATOR
    if any(token in name for token in ("subprocesserror", "calledprocesserror")):
        return FailureKind.EPISODE_RUNTIME
    return FailureKind.UNKNOWN


def verify_dataset_snapshot(
    snapshot_path: str | Path,
    cases_root: str | Path | None = None,
) -> dict[str, Any]:

    path = Path(snapshot_path).resolve()
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    root = Path(cases_root).resolve() if cases_root else path.parent.parent / "cases"
    errors: list[dict[str, str]] = []
    seen_files: set[str] = set()
    seen_ids: set[str] = set()
    entries = snapshot.get("cases", [])
    if snapshot.get("case_count") != len(entries):
        errors.append({"kind": "count_mismatch", "detail": "case_count does not match cases"})
    for entry in entries:
        filename = str(entry.get("file", ""))
        case_id = str(entry.get("case_id", ""))
        if filename in seen_files or case_id in seen_ids:
            errors.append({"kind": "duplicate", "detail": filename or case_id})
            continue
        seen_files.add(filename)
        seen_ids.add(case_id)
        candidate = (root / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append({"kind": "path_escape", "detail": filename})
            continue
        if not candidate.is_file():
            errors.append({"kind": "missing", "detail": filename})
            continue
        actual_hash = file_sha256(candidate)
        if actual_hash != entry.get("sha256"):
            errors.append({"kind": "sha256_mismatch", "detail": filename})
            continue
        try:
            case = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"kind": "invalid_json", "detail": f"{filename}: {type(exc).__name__}"})
            continue
        if case.get("case_id") != case_id:
            errors.append({"kind": "case_id_mismatch", "detail": filename})
    return {
        "valid": not errors,
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_path": str(path),
        "snapshot_sha256": file_sha256(path),
        "cases_root": str(root),
        "case_count": len(entries),
        "errors": errors,
    }


def build_episodes_from_snapshot(
    snapshot_path: str | Path,
    conditions: Iterable[str],
    trials: int,
) -> list[EpisodeSpec]:
    if trials < 1:
        raise ValueError("trials must be positive")
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    episodes = []
    for trial in range(trials):
        for entry in snapshot["cases"]:
            for condition in conditions:
                episode_id = f"{entry['case_id']}--{condition}--trial-{trial:03d}"
                episodes.append(EpisodeSpec(
                    episode_id=episode_id,
                    case_id=entry["case_id"],
                    condition=condition,
                    trial=trial,
                    payload={
                        "case_file": entry["file"],
                        "phase": entry.get("phase"),
                        "domain": entry.get("domain"),
                        "capability_score_eligible": entry.get("capability_score_eligible"),
                        "case_sha256": entry["sha256"],
                    },
                ))
    return episodes


Worker = Callable[[EpisodeSpec, AttemptContext], Mapping[str, Any]]


class ExperimentManager:


    def __init__(
        self,
        output_root: str | Path,
        run_id: str,
        experiment_config: Mapping[str, Any],
        episodes: Iterable[EpisodeSpec],
        *,
        dataset_snapshot: str | Path | None = None,
        cases_root: str | Path | None = None,
        max_concurrency: int = 1,
        retry_policy: RetryPolicy | None = None,
        provider_profiles: Iterable[str] = (),
        resume: bool = True,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        safe_run_id = _SAFE_ID.sub("_", run_id).strip("._")
        if not safe_run_id or safe_run_id != run_id:
            raise ValueError("run_id may contain only letters, digits, dot, dash, underscore")
        self.run_id = run_id
        self.run_dir = (Path(output_root).resolve() / run_id)
        self.manifest_path = self.run_dir / "manifest.json"
        self.lock_path = self.run_dir / ".manager.lock"
        self.checkpoints_dir = self.run_dir / "checkpoints"
        self.workspaces_dir = self.run_dir / "workspaces"
        self.max_concurrency = max_concurrency
        self.retry_policy = retry_policy or RetryPolicy()
        self.provider_profiles = tuple(provider_profiles)
        self.specs = list(episodes)
        if len({spec.episode_id for spec in self.specs}) != len(self.specs):
            raise ValueError("episode_id values must be unique")
        self.spec_by_id = {spec.episode_id: spec for spec in self.specs}
        self.dataset = None
        if dataset_snapshot:
            self.dataset = verify_dataset_snapshot(dataset_snapshot, cases_root)
            if not self.dataset["valid"]:
                raise ValueError(f"dataset snapshot verification failed: {self.dataset['errors']}")
        fingerprint_input = {
            "schema_version": SCHEMA_VERSION,
            "experiment_config": experiment_config,
            "episodes": [spec.to_dict() for spec in self.specs],
            "dataset": self.dataset,
            "retry_policy": self.retry_policy.to_dict(),
            "provider_profiles": self.provider_profiles,
        }
        self.config_fingerprint = canonical_fingerprint(fingerprint_input)
        self.experiment_config = redact_secrets(experiment_config)
        self._manifest = self._load_or_create(resume)
        self._recover_checkpoints()
        self._checkpoint_manifest()

    def _load_or_create(self, resume: bool) -> dict[str, Any]:
        if self.manifest_path.exists():
            if not resume:
                raise FileExistsError(f"run already exists: {self.run_dir}")
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if manifest.get("config_fingerprint") != self.config_fingerprint:
                raise ValueError(
                    "experiment config fingerprint differs from the existing run; "
                    "use a new run_id instead of mixing models, providers, cases, "
                    "arms, or retry policies in one manifest"
                )
            return manifest
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": "RUNNING",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "config_fingerprint": self.config_fingerprint,
            "experiment_config": self.experiment_config,
            "dataset": self.dataset,
            "manager": {
                "max_concurrency": self.max_concurrency,
                "retry_policy": self.retry_policy.to_dict(),
                "provider_profiles": list(self.provider_profiles),
                "workspace_layout": "workspaces/<episode_id>/attempt-NNN/",
            },
            "episodes": {
                spec.episode_id: {
                    "spec": spec.to_dict(),
                    "status": EpisodeStatus.PENDING.value,
                    "attempts": [],
                    "resume_count": 0,
                }
                for spec in self.specs
            },
            "aggregate": {},
        }

    def _checkpoint_path(self, episode_id: str) -> Path:
        safe_id = _SAFE_ID.sub("_", episode_id)
        suffix = hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:12]
        return self.checkpoints_dir / f"{safe_id[:120]}--{suffix}.json"

    @staticmethod
    def _episode_storage_name(episode_id: str) -> str:

        suffix = hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:12]
        return f"ep-{suffix}"

    def _recover_checkpoints(self) -> None:
        for episode_id, state in self._manifest["episodes"].items():
            path = self._checkpoint_path(episode_id)
            if path.exists():
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                if checkpoint.get("episode_id") == episode_id:
                    self._manifest["episodes"][episode_id] = checkpoint["state"]
                    state = self._manifest["episodes"][episode_id]
            if state["status"] == EpisodeStatus.RUNNING.value:
                attempts = state.setdefault("attempts", [])
                if attempts and attempts[-1].get("status") == EpisodeStatus.RUNNING.value:
                    attempts[-1].update({
                        "status": EpisodeStatus.FAILED_RETRYABLE.value,
                        "finished_at": utc_now(),
                        "failure": {
                            "kind": FailureKind.INTERRUPTED.value,
                            "error_type": "InterruptedRun",
                            "message": "Previous process ended before the attempt checkpoint completed.",
                            "retryable": True,
                        },
                    })
                state["resume_count"] = int(state.get("resume_count", 0)) + 1
                state["status"] = (
                    EpisodeStatus.PENDING.value
                    if len(attempts) < self.retry_policy.max_attempts
                    else EpisodeStatus.FAILED_TERMINAL.value
                )
                self._checkpoint_episode(episode_id)

    def _checkpoint_episode(self, episode_id: str) -> None:
        write_atomic(self._checkpoint_path(episode_id), {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "episode_id": episode_id,
            "updated_at": utc_now(),
            "state": self._manifest["episodes"][episode_id],
        })

    def _checkpoint_manifest(self) -> None:
        self._manifest["updated_at"] = utc_now()
        self._manifest["aggregate"] = self.aggregate()
        write_atomic(self.manifest_path, self._manifest)

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":


            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True

            return ctypes.get_last_error() == 5
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @contextmanager
    def _run_lock(self):

        self.run_dir.mkdir(parents=True, exist_ok=True)
        lock_record = {
            "run_id": self.run_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": utc_now(),
        }
        while True:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                try:
                    existing = json.loads(self.lock_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
                same_host = existing.get("hostname") == socket.gethostname()
                active = same_host and self._pid_is_alive(int(existing.get("pid") or 0))
                if active:
                    raise RuntimeError(
                        f"experiment run is already active under pid={existing.get('pid')}"
                    )


                try:
                    self.lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(lock_record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            break
        try:
            yield
        finally:
            try:
                current = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = {}
            if current.get("pid") == os.getpid():
                try:
                    self.lock_path.unlink()
                except FileNotFoundError:
                    pass

    def _provider_for_attempt(self, attempt: int) -> str | None:
        if not self.provider_profiles:
            return None
        return self.provider_profiles[min(attempt - 1, len(self.provider_profiles) - 1)]

    def _start_attempt(self, episode_id: str) -> tuple[EpisodeSpec, AttemptContext]:
        state = self._manifest["episodes"][episode_id]
        attempt_number = len(state["attempts"]) + 1
        workspace = (
            self.workspaces_dir
            / self._episode_storage_name(episode_id)
            / f"a-{attempt_number:03d}"
        )
        workspace.mkdir(parents=True, exist_ok=False)
        marker = {
            "run_id": self.run_id,
            "episode_id": episode_id,
            "attempt": attempt_number,
            "created_at": utc_now(),
        }
        write_atomic(workspace / 'artifact.experiment_workspace.json', marker)
        attempt = {
            "attempt": attempt_number,
            "status": EpisodeStatus.RUNNING.value,
            "started_at": utc_now(),
            "finished_at": None,
            "workspace": str(workspace),
            "provider_profile": self._provider_for_attempt(attempt_number),
        }
        state["attempts"].append(attempt)
        state["status"] = EpisodeStatus.RUNNING.value
        self._checkpoint_episode(episode_id)
        self._checkpoint_manifest()
        return self.spec_by_id[episode_id], AttemptContext(
            run_id=self.run_id,
            attempt=attempt_number,
            workspace=workspace,
            provider_profile=attempt["provider_profile"],
        )

    def _run_worker(self, worker: Worker, spec: EpisodeSpec, context: AttemptContext) -> dict[str, Any]:
        delay = self.retry_policy.delay(context.attempt - 1)
        if delay:
            time.sleep(delay)
        started = time.perf_counter()
        try:
            result = worker(spec, context)
            if not isinstance(result, Mapping):
                raise ExperimentFailure(
                    FailureKind.MODEL_RESPONSE_CONTRACT,
                    "episode worker must return a mapping",
                )
            safe_result = redact_secrets(result)
            json.dumps(safe_result, ensure_ascii=False)
            return {
                "ok": True,
                "result": safe_result,
                "wall_seconds": round(time.perf_counter() - started, 4),
            }
        except Exception as exc:
            if isinstance(exc, ExperimentFailure):
                kind = exc.kind
                retryable = exc.retryable
                details = exc.details
            else:
                kind = classify_exception(exc)
                retryable = None
                details = {}
            if retryable is None:
                retryable = kind in self.retry_policy.retryable_failures
            return {
                "ok": False,
                "wall_seconds": round(time.perf_counter() - started, 4),
                "failure": {
                    "kind": kind.value,
                    "error_type": type(exc).__name__,
                    "message": redact_secrets(str(exc)[:1000]),
                    "retryable": bool(retryable),
                    "details": redact_secrets(details),
                },
            }

    def _finish_attempt(self, episode_id: str, outcome: Mapping[str, Any]) -> None:
        state = self._manifest["episodes"][episode_id]
        attempt = state["attempts"][-1]
        attempt["finished_at"] = utc_now()
        attempt["wall_seconds"] = outcome.get("wall_seconds")
        if outcome["ok"]:
            attempt["status"] = EpisodeStatus.SUCCEEDED.value
            attempt["result"] = outcome["result"]
            state["status"] = EpisodeStatus.SUCCEEDED.value
        else:
            attempt["failure"] = outcome["failure"]
            retryable = bool(outcome["failure"]["retryable"])
            attempts_left = len(state["attempts"]) < self.retry_policy.max_attempts
            if retryable and attempts_left:
                attempt["status"] = EpisodeStatus.FAILED_RETRYABLE.value
                state["status"] = EpisodeStatus.FAILED_RETRYABLE.value
            else:
                attempt["status"] = EpisodeStatus.FAILED_TERMINAL.value
                state["status"] = EpisodeStatus.FAILED_TERMINAL.value
        self._checkpoint_episode(episode_id)
        self._checkpoint_manifest()

    def _runnable(self) -> list[str]:
        runnable = []
        for spec in self.specs:
            state = self._manifest["episodes"][spec.episode_id]
            if state["status"] in {
                EpisodeStatus.PENDING.value,
                EpisodeStatus.FAILED_RETRYABLE.value,
            } and len(state["attempts"]) < self.retry_policy.max_attempts:
                runnable.append(spec.episode_id)
        return runnable

    def _next_provider_profile(self, episode_id: str) -> str | None:

        state = self._manifest["episodes"][episode_id]
        return self._provider_for_attempt(len(state["attempts"]) + 1)

    def _homogeneous_wave(self, runnable: list[str]) -> list[str]:

        if not runnable:
            return []
        if len(self.provider_profiles) <= 1:
            return runnable[: self.max_concurrency]
        head_profile = self._next_provider_profile(runnable[0])
        wave = [
            episode_id
            for episode_id in runnable
            if self._next_provider_profile(episode_id) == head_profile
        ]
        return wave[: self.max_concurrency]

    def run(self, worker: Worker) -> dict[str, Any]:
        with self._run_lock():
            self._manifest["status"] = "RUNNING"
            self._checkpoint_manifest()
            try:
                while True:
                    runnable = self._runnable()
                    if not runnable:
                        break
                    wave = self._homogeneous_wave(runnable)
                    with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
                        futures = {}
                        for episode_id in wave:
                            spec, context = self._start_attempt(episode_id)
                            futures[pool.submit(self._run_worker, worker, spec, context)] = episode_id
                        for future in as_completed(futures):
                            self._finish_attempt(futures[future], future.result())
            except KeyboardInterrupt:
                self._manifest["status"] = "INTERRUPTED"
                self._checkpoint_manifest()
                raise
            terminal_failures = sum(
                state["status"] == EpisodeStatus.FAILED_TERMINAL.value
                for state in self._manifest["episodes"].values()
            )
            self._manifest["status"] = "COMPLETE_WITH_FAILURES" if terminal_failures else "COMPLETE"
            self._manifest["finished_at"] = utc_now()
            self._checkpoint_manifest()
            return redact_secrets(self._manifest)

    @staticmethod
    def _usage(result: Mapping[str, Any]) -> dict[str, float | int]:
        metrics = result.get("api_metrics") or result.get("api_call_metrics") or []
        if not isinstance(metrics, list):
            metrics = []
        usage: dict[str, float | int] = {
            "calls": len(metrics),
            "failed_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": 0.0,
            "cost_usd": float(result.get("cost_usd") or 0.0),
        }
        for metric in metrics:
            if not isinstance(metric, Mapping):
                continue
            usage["failed_calls"] += int(metric.get("ok") is False)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = metric.get(field)
                if isinstance(value, int):
                    usage[field] += value
            latency = metric.get("latency_seconds", metric.get("elapsed_seconds", 0))
            if isinstance(latency, (int, float)):
                usage["latency_seconds"] += float(latency)
            cost = metric.get("cost_usd")
            if isinstance(cost, (int, float)):
                usage["cost_usd"] += float(cost)
        usage["latency_seconds"] = round(float(usage["latency_seconds"]), 4)
        usage["cost_usd"] = round(float(usage["cost_usd"]), 8)
        return usage

    def aggregate(self) -> dict[str, Any]:
        statuses = Counter()
        failure_kinds = Counter()
        by_condition: dict[str, Counter] = defaultdict(Counter)
        usage: dict[str, float | int] = {
            "calls": 0,
            "failed_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": 0.0,
            "cost_usd": 0.0,
        }
        attempts = 0
        for state in self._manifest.get("episodes", {}).values():
            status = state["status"]
            condition = state["spec"]["condition"]
            statuses[status] += 1
            by_condition[condition][status] += 1
            attempts += len(state.get("attempts", []))
            for attempt in state.get("attempts", []):
                failure = attempt.get("failure")
                if failure:
                    failure_kinds[failure["kind"]] += 1
                result = attempt.get("result")
                if isinstance(result, Mapping):
                    item_usage = self._usage(result)
                    for field in usage:
                        usage[field] += item_usage[field]
        usage["latency_seconds"] = round(float(usage["latency_seconds"]), 4)
        usage["cost_usd"] = round(float(usage["cost_usd"]), 8)
        return {
            "episodes": len(self._manifest.get("episodes", {})),
            "attempts": attempts,
            "status_counts": dict(statuses),
            "failure_counts": dict(failure_kinds),
            "by_condition": {key: dict(value) for key, value in by_condition.items()},
            "usage": usage,
        }
