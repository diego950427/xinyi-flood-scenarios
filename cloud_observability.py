"""Best-effort resource evidence for the hosting log; no model or user secrets.

The sum of process RSS can count shared pages more than once. Linux cgroup
memory.current is the container measurement; neither is an OOM diagnosis.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import time

import psutil


def collect_resource_snapshot(cgroup_root=Path('/sys/fs/cgroup'), process=None):
    process = process or psutil.Process()
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except psutil.Error:
        pass
    rss, sampled = 0, 0
    for child in processes:
        try:
            rss += child.memory_info().rss
            sampled += 1
        except psutil.Error:
            pass
    snapshot = {'process_tree_rss_bytes': rss if sampled else None,
                'process_tree_sampled_count': sampled}
    for filename, key in [('memory.current', 'cgroup_memory_current_bytes'),
                          ('memory.max', 'cgroup_memory_max_bytes')]:
        try:
            value = (cgroup_root / filename).read_text(encoding='ascii').strip()
            snapshot[key] = 'max' if value == 'max' else int(value)
        except (OSError, ValueError):
            snapshot[key] = None
    return snapshot


def log_progress_resources(state, run_id, phase, progress_s=None, end_s=None,
                           *, now=None, sampler=collect_resource_snapshot, emit=print):
    """Log each observed phase change, otherwise at most once per 60 seconds.

    State belongs to this browser session. Only the explicit fields below are
    emitted: no session state, owner token, exception text, or filesystem paths.
    """
    now = time.monotonic() if now is None else now
    previous = state.get('cloud_resource_log', {})
    changed = previous.get('run_id') != run_id or previous.get('phase') != phase
    if not changed and now - previous.get('at', now) < 60:
        return None
    record = {'event': 'xinyi_resource',
              'observed_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'run_id': run_id, 'phase': phase,
              'progress_hours': None if progress_s is None else round(progress_s / 3600, 6),
              'end_hours': None if end_s is None else round(end_s / 3600, 6)}
    try:
        record.update(sampler())
    except Exception as exc:
        # Monitoring must not interrupt a calculation or expose error paths.
        record['resource_sample_error'] = type(exc).__name__
    try:
        emit(json.dumps(record, ensure_ascii=True, allow_nan=False), flush=True)
    except (OSError, ValueError):
        return None
    state['cloud_resource_log'] = {'run_id': run_id, 'phase': phase, 'at': now}
    return record
