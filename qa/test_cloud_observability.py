"""Resource-log checks only; no native solver, GUI, or cloud connection."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cloud_observability import collect_resource_snapshot, log_progress_resources

checks = {}
actual = collect_resource_snapshot()
checks['actual_local_process_sample'] = (actual['process_tree_rss_bytes'] > 0
                                         and actual['process_tree_sampled_count'] >= 1)
child = Mock()
child.memory_info.return_value = SimpleNamespace(rss=200)
process = Mock()
process.children.return_value = [child]
process.memory_info.return_value = SimpleNamespace(rss=100)
with patch('cloud_observability.Path.read_text', side_effect=['3456\n', '7890\n']):
    sample = collect_resource_snapshot(process=process)
checks['process_tree_and_cgroup_values'] = (sample['process_tree_rss_bytes'] == 300
    and sample['process_tree_sampled_count'] == 2
    and sample['cgroup_memory_current_bytes'] == 3456
    and sample['cgroup_memory_max_bytes'] == 7890)
with patch('cloud_observability.Path.read_text', side_effect=['3456\n', 'max\n']):
    checks['unlimited_cgroup_is_explicit'] = collect_resource_snapshot(process=process)['cgroup_memory_max_bytes'] == 'max'

state = {'owner_token': 'never-log-this-token', 'private_path': 'never-log-this-path'}
lines = []
def emit(line, **kwargs):
    lines.append(line)
kwargs = {'sampler': lambda: sample, 'emit': emit}
first = log_progress_resources(state, 'test_run', 'running', 3600, 25200, now=0, **kwargs)
suppressed = log_progress_resources(state, 'test_run', 'running', 3660, 25200, now=59, **kwargs)
periodic = log_progress_resources(state, 'test_run', 'running', 3720, 25200, now=60, **kwargs)
finishing = log_progress_resources(state, 'test_run', 'finishing', 25200, 25200, now=61, **kwargs)
completed = log_progress_resources(state, 'test_run', 'completed', 25200, 25200, now=62, **kwargs)
checks['sixty_second_interval'] = first is not None and suppressed is None and periodic is not None
checks['phase_changes_log_immediately'] = finishing is not None and completed is not None
checks['progress_units_and_log_fields'] = (first['progress_hours'] == 1 and first['end_hours'] == 7
    and all(json.loads(line)['event'] == 'xinyi_resource' for line in lines))
checks['no_session_secrets_or_private_paths'] = all('never-log-' not in line and 'owner_token' not in line for line in lines)
def unavailable():
    raise OSError('never-log-this-error-path')
failure = log_progress_resources({}, 'test_run', 'running', now=0, sampler=unavailable, emit=emit)
checks['sampling_failure_does_not_break_ui'] = (failure['resource_sample_error'] == 'OSError'
    and 'never-log-' not in lines[-1])
report = {'passed': all(checks.values()), 'checks': checks, 'actual_local_sample': actual,
          'scope': 'Local resource helper, timing, phase and privacy checks; no cloud memory or solver claim.'}
(ROOT / 'qa/cloud_observability_tests.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
assert report['passed']
