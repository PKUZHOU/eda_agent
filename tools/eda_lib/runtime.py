#!/usr/bin/env python3
"""Linux execution endpoint and detached worker; Python 3.6 standard library."""
import base64
import datetime
import fcntl
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

VERSION = 1
ACTIVE = ('queued', 'running')
TERMINAL = ('completed', 'failed', 'timed_out', 'cancelled', 'interrupted')
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
TOOL_ERRORS = [r'^\s*Error:', r'^\s*Fatal:', r'^\s*FATAL:', r'^\s*Error-\[',
               r'^\s*UVM_(?:ERROR|FATAL)\s+[^:]', r'^\s*Traceback \(most recent call last\):']
BLOCKING_FINDINGS = ['invalid_parasitic_timing_evidence', 'nonzero_drc_observed',
                     'open_nets_observed', 'tool_error_observed']


class RequestError(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load(path):
    with Path(path).open() as stream:
        return json.load(stream)


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def lock(path):
    with Path(path).open('a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield stream


def identifier(value):
    if not isinstance(value, str) or not NAME.fullmatch(value) or value in ('.', '..'):
        raise RequestError('Invalid run/stage identifier')
    return value


def relative(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise RequestError('Expected a relative path')
    p = Path(value)
    if p.is_absolute() or '..' in p.parts or value == '.':
        raise RequestError('Path must stay inside the run: ' + value)
    return p


def within(root, value):
    p = Path(root) / relative(value)
    cursor = p
    while cursor != Path(root):
        if cursor.is_symlink():
            raise RequestError('Symlink in run path: ' + value)
        cursor = cursor.parent
    try:
        p.resolve().relative_to(Path(root).resolve())
    except ValueError:
        raise RequestError('Path escapes run directory: ' + value)
    return p


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tree(path):
    """Hash a declared file/tree; reject symlinks and special files."""
    path = Path(path)
    if not path.exists() or path.is_symlink():
        raise RequestError('Missing or symlinked input/artifact: ' + str(path))
    if not path.is_file() and not path.is_dir():
        raise RequestError('Special file in declared input/artifact: ' + str(path))
    paths = [path] if path.is_file() else sorted(path.rglob('*'))
    result = {}
    for p in paths:
        if p.is_symlink():
            raise RequestError('Symlink in declared input/artifact: ' + str(p))
        key = '.' if p == path else p.relative_to(path).as_posix()
        if p.is_file():
            result[key] = {'kind': 'file', 'size': p.stat().st_size, 'sha256': sha(p)}
        elif p.is_dir():
            result[key] = {'kind': 'directory'}
        else:
            raise RequestError('Special file in declared input/artifact: ' + str(p))
    return {'kind': 'file' if path.is_file() else 'directory', 'entries': result}


def stamp(path):
    path = Path(path)
    if not path.exists():
        return None
    tree(path)  # Also reject escaping symlinks.
    paths = [path] + (sorted(path.rglob('*')) if path.is_dir() else [])
    return [(str(p.relative_to(path)) if p != path else '.', p.stat().st_size,
             p.stat().st_mtime_ns, p.stat().st_ino) for p in paths]


def copy_path(source, destination):
    tree(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(str(destination))
        else:
            destination.unlink()
    if Path(source).is_dir():
        shutil.copytree(str(source), str(destination))
    else:
        shutil.copy2(str(source), str(destination))


def number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise RequestError('Invalid ' + name)
    return value


def validate(profile, flow):
    if not isinstance(profile, dict) or not isinstance(flow, dict):
        raise RequestError('Profile and flow must be objects')
    for key in ('resources', 'tools', 'env'):
        if not isinstance(profile.get(key, {}), dict):
            raise RequestError(key + ' must be an object')
    for key, value in profile.get('env', {}).items():
        if not isinstance(key, str) or not key or '=' in key or '\x00' in key or not isinstance(value, str) or '\x00' in value:
            raise RequestError('Environment must contain valid string keys/values')
    for value in profile.get('tools', {}).values():
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise RequestError('Tool paths must be absolute')
    if profile.get('version') != VERSION or flow.get('version') != VERSION:
        raise RequestError('Profile and flow must specify version: 1')
    for key in ('project_root', 'run_root'):
        if not isinstance(profile.get(key), str) or not Path(profile[key]).is_absolute():
            raise RequestError(key + ' must be an absolute execution-host path')
    if Path(profile['project_root']).resolve() == Path(profile['run_root']).resolve():
        raise RequestError('run_root must differ from project_root')
    if profile.get('resources', {}).get('max_concurrent_heavy_jobs', 1) != 1:
        raise RequestError('Version 1 supports one heavy job per run_root')
    resources = profile.get('resources', {})
    threads = resources.get('threads_per_job', 4)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise RequestError('threads_per_job must be a positive integer')
    number(resources.get('min_free_memory_gib', 0), 'min_free_memory_gib')
    if resources.get('memory_limit_gib') is not None:
        number(resources['memory_limit_gib'], 'memory_limit_gib', 0.01)
    number(flow.get('budget_seconds'), 'budget_seconds', 0.1)
    if flow.get('isolation') != 'reviewed_run_directory':
        raise RequestError('Flow adapter must declare reviewed_run_directory isolation')
    inputs = flow.get('inputs')
    if not isinstance(inputs, list) or not inputs:
        raise RequestError('Declare inputs explicitly')
    destinations = []
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get('source'), str):
            raise RequestError('Input source must be a path')
        d = relative(item['destination'])
        if any(d == x or d in x.parents or x in d.parents for x in destinations):
            raise RequestError('Overlapping input destinations')
        destinations.append(d)
    if not isinstance(flow.get('external_inputs', []), list) or any(not isinstance(x, str) for x in flow.get('external_inputs', [])):
        raise RequestError('external_inputs must be an array of paths')
    stages = flow.get('stages')
    if not isinstance(stages, list) or not stages:
        raise RequestError('Flow needs ordered stages')
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise RequestError('Each stage must be an object')
        name = identifier(stage.get('id'))
        if name in seen:
            raise RequestError('Duplicate stage id')
        seen.add(name)
        if stage.get('tool', 'command') not in ('command', 'dc_shell', 'icc2_shell', 'pt_shell'):
            raise RequestError('Unsupported tool adapter')
        argv_check(stage.get('argv'))
        number(stage.get('timeout_seconds'), 'stage timeout', 0.1)
        number(stage.get('minimum_start_seconds', 0.1), 'minimum_start_seconds', 0.1)
        if stage.get('cwd', '.') != '.':
            relative(stage['cwd'])
        if not stage.get('success_pattern'):
            raise RequestError('Every stage requires a success_pattern')
        re.compile(stage['success_pattern'])
        for pattern in stage.get('error_patterns', []):
            re.compile(pattern)
        outputs = stage.get('outputs', [])
        if not isinstance(outputs, list) or not outputs:
            raise RequestError('Every stage requires declared outputs')
        output_paths = []
        for output in outputs:
            p = relative(output['path'])
            if any(p == x or p in x.parents or x in p.parents for x in output_paths):
                raise RequestError('Overlapping output paths within stage')
            output_paths.append(p)
            if output.get('kind', 'artifact') not in ('report', 'artifact', 'checkpoint'):
                raise RequestError('Unknown artifact kind')
        checkpoint = stage.get('checkpoint')
        if checkpoint:
            if not checkpoint.get('paths'):
                raise RequestError('Checkpoint must declare paths')
            checkpoint_paths = []
            for path in checkpoint['paths']:
                p = relative(path)
                if p.parts[0] == 'checkpoint.json' or any(p == x or p in x.parents or x in p.parents for x in checkpoint_paths):
                    raise RequestError('Overlapping/reserved checkpoint paths')
                checkpoint_paths.append(p)
            probe = checkpoint.get('restore_probe', {})
            argv_check(probe.get('argv'))
            number(probe.get('timeout_seconds'), 'restore probe timeout', 0.1)
            if not probe.get('success_pattern'):
                raise RequestError('Checkpoint requires a native restore probe marker')
            re.compile(probe['success_pattern'])
        if stage.get('qor_manifest'):
            if relative(stage['qor_manifest']) not in output_paths:
                raise RequestError('qor_manifest must be a declared fresh output')
    return profile, flow


def argv_check(argv):
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or '\x00' in x for x in argv):
        raise RequestError('argv must be a nonempty array of strings')


def command(argv, profile, work):
    result = []
    for arg in argv:
        if arg.startswith('{tool:') and arg.endswith('}'):
            name = arg[6:-1]
            if name not in profile.get('tools', {}):
                raise RequestError('Tool is not configured: ' + name)
            arg = profile['tools'][name]
        else:
            arg = arg.replace('{run_dir}', str(work)).replace('{python}', sys.executable)
        result.append(arg)
    return result


def input_identity(profile, flow):
    result = {'inputs': [], 'external_inputs': []}
    for item in flow['inputs']:
        source = Path(item['source'])
        if not source.is_absolute():
            source = Path(profile['project_root']) / source
        source = source.absolute()
        try:
            Path(profile['run_root']).resolve().relative_to(source.resolve())
            raise RequestError('Input includes run_root and would recursively capture runs')
        except ValueError:
            pass
        result['inputs'].append({'source': str(source), 'destination': item['destination'], 'tree': tree(source)})
    for raw in flow.get('external_inputs', []):
        source = Path(raw)
        if not source.is_absolute():
            source = Path(profile['project_root']) / source
        result['external_inputs'].append({'source': str(source.absolute()), 'tree': tree(source)})
    return result


def available_memory():
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / (1024.0 * 1024.0)
    except OSError:
        pass
    return None


def preflight(profile, flow):
    validate(profile, flow)
    errors = []
    checks = []
    project = Path(profile['project_root'])
    if not project.is_dir():
        errors.append('project_root is not a directory')
    parent = Path(profile['run_root'])
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.is_dir() or not os.access(str(parent), os.W_OK):
        errors.append('run_root cannot be created/written')
    for stage in flow['stages']:
        for spec in [stage] + ([stage['checkpoint']['restore_probe']] if stage.get('checkpoint') else []):
            argv = command(spec['argv'], profile, project)
            executable = argv[0]
            exists = Path(executable).is_file() and os.access(executable, os.X_OK) if '/' in executable else shutil.which(executable) is not None
            checks.append({'stage': stage['id'], 'executable': executable, 'available': exists})
            if not exists:
                errors.append('Executable unavailable: ' + executable)
        tool = stage.get('tool', 'command')
        if tool != 'command':
            executable = profile.get('tools', {}).get(tool)
            if not executable or not Path(executable).is_file() or not os.access(executable, os.X_OK):
                errors.append('Configured native tool unavailable: ' + tool)
    resources = profile.get('resources', {})
    if resources.get('threads_per_job', 4) > (os.cpu_count() or 1):
        errors.append('Requested threads exceed execution-host CPU count')
    memory = available_memory()
    if resources.get('min_free_memory_gib', 0) and (memory is None or memory < resources['min_free_memory_gib']):
        errors.append('Insufficient observable available memory')
    identities = None
    try:
        identities = input_identity(profile, flow)
    except (OSError, RequestError) as error:
        errors.append(str(error))
    return {'ready': not errors, 'errors': errors, 'checks': checks, 'available_memory_gib': memory,
            'cpu_count': os.cpu_count(), 'input_identity': identities,
            'limitations': ['Executable presence does not verify license checkout or tool version.',
                            'Reviewed project adapters are trusted scripts, not an arbitrary-Tcl sandbox.',
                            'EDA_THREADS is supplied; the project adapter must apply native thread controls.']}


def fingerprint(profile, flow):
    execution_profile = {k: v for k, v in profile.items() if k != 'transport'}
    return hashlib.sha256(json.dumps({'profile': execution_profile, 'flow': flow}, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def identity(pid):
    try:
        content = Path('/proc/{}/stat'.format(pid)).read_text()
        fields = content[content.rfind(')') + 2:].split()
        return {'pid': int(pid), 'start_ticks': fields[19], 'pgrp': int(fields[2]),
                'session': int(fields[3]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'uid': Path('/proc/{}'.format(pid)).stat().st_uid, 'state': fields[0]}
    except (OSError, IndexError, ValueError):
        return None


def alive(token):
    if not token:
        return False
    current = identity(token['pid'])
    return bool(current and current['state'] != 'Z' and all(current[k] == token[k]
                for k in ('pid', 'start_ticks', 'boot_id', 'uid')))


def group_members(token):
    if not token or token.get('uid') != os.getuid():
        return []
    if token.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        return []
    leader = identity(token['pid'])
    if leader and (leader['start_ticks'] != token['start_ticks'] or leader['uid'] != token['uid']):
        return []
    members = []
    for p in Path('/proc').iterdir():
        if p.name.isdigit():
            item = identity(int(p.name))
            if item and item['uid'] == token['uid'] and item['pgrp'] == token['pgrp'] and item['session'] == token['session'] and item['state'] != 'Z':
                members.append(item)
    return members


def stop_group(token):
    if not group_members(token):
        return
    try:
        os.killpg(token['pgrp'], signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 3
    while group_members(token) and time.monotonic() < deadline:
        time.sleep(0.1)
    if group_members(token):
        try:
            os.killpg(token['pgrp'], signal.SIGKILL)
        except ProcessLookupError:
            pass


def group_rss(token):
    total = 0
    for item in group_members(token):
        try:
            for line in Path('/proc/{}/status'.format(item['pid'])).read_text().splitlines():
                if line.startswith('VmRSS:'):
                    total += int(line.split()[1]) * 1024
        except OSError:
            pass
    return total


def state_save(run, state):
    state['updated_at'] = now()
    atomic(run / 'state.json', state)
    atomic(run / 'attempts' / str(state['attempt']) / 'state.json', state)


def event(run, kind, **values):
    with (run / 'events.jsonl').open('a') as stream:
        stream.write(json.dumps(dict(time=now(), event=kind, **values), ensure_ascii=False) + '\n')
        stream.flush()


def state_read(run):
    state = load(run / 'state.json')
    if state['status'] in ACTIVE and not alive(state.get('worker')):
        state['status'] = 'interrupted'
        state['result_validity'] = 'insufficient'
        state['reason'] = 'worker_missing_or_host_restarted'
        state['active_tool_detected'] = bool(group_members(state.get('tool_process')))
        state_save(run, state)
        event(run, 'interrupted', reason=state['reason'])
    return state


def runtime_files(root, sources):
    content = sources['runtime'] + sources['qor']
    key = hashlib.sha256(content.encode()).hexdigest()
    directory = root / '.runtime' / key
    directory.mkdir(parents=True, exist_ok=True)
    for name, key_name in [('runtime.py', 'runtime'), ('qor.py', 'qor')]:
        path = directory / name
        if not path.exists():
            path.write_text(sources[key_name])
        if path.read_text() != sources[key_name]:
            raise RequestError('Runtime bundle checksum mismatch')
    return directory


def launch(run, state, runtime):
    attempt = run / 'attempts' / str(state['attempt'])
    attempt.mkdir(parents=True, exist_ok=True)
    state_save(run, state)
    with (attempt / 'worker.log').open('ab') as stream:
        process = subprocess.Popen([sys.executable, str(runtime / 'runtime.py'), '_worker', str(run), str(state['attempt'])],
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
    state['worker'] = identity(process.pid)
    if not state['worker']:
        raise RequestError('Worker failed to start')
    state_save(run, state)
    event(run, 'submitted', attempt=state['attempt'], worker_pid=process.pid)
    return state


def submit(profile, flow, run_id, sources):
    validate(profile, flow)
    root = Path(profile['run_root'])
    root.mkdir(parents=True, exist_ok=True)
    run = root / identifier(run_id)
    fp = fingerprint(profile, flow)
    with lock(root / '.submit.lock'):
        if run.exists():
            if not (run / 'request.json').exists():
                raise RequestError('Incomplete existing run; preserve it and use a new run_id')
            if load(run / 'request.json')['fingerprint'] != fp:
                raise RequestError('run_id already exists with different configuration')
            with lock(run / '.control.lock'):
                return dict(state_read(run), reused=True)
        check = preflight(profile, flow)
        if not check['ready']:
            raise RequestError('Preflight failed: ' + '; '.join(check['errors']))
        runtime = runtime_files(root, sources)
        run.mkdir()
        (run / 'inputs').mkdir()
        for item in check['input_identity']['inputs']:
            destination = within(run / 'inputs', item['destination'])
            copy_path(item['source'], destination)
            if tree(destination) != item['tree']:
                raise RequestError('Input changed during capture')
        atomic(run / 'request.json', {'version': 1, 'profile': profile, 'flow': flow, 'fingerprint': fp,
            'input_identity': check['input_identity'], 'runtime_dir': str(runtime), 'created_at': now()})
        state = {'run_id': run_id, 'attempt': 1, 'status': 'queued', 'result_validity': 'insufficient',
            'validation_scope': 'declared stage checks, not signoff', 'qor_comparable': False,
            'pipeline_complete': False,
            'created_at': now(), 'stages': [], 'worker': None, 'tool_process': None,
            'start_index': 0, 'resume_from': None, 'reason': None}
        with lock(run / '.control.lock'):
            return launch(run, state, runtime)


def audit_reports(runtime, report_paths):
    spec = importlib.util.spec_from_file_location('eda_qor', str(runtime / 'qor.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reports = [module.audit(path) for path in report_paths]
    return module, reports


def evaluate(stage, work, log, outputs, runtime):
    text = log.read_text(errors='replace')
    errors = []
    if not re.search(stage['success_pattern'], text, re.M):
        errors.append('completion_marker_missing')
    for pattern in TOOL_ERRORS + stage.get('error_patterns', []):
        match = re.search(pattern, text, re.M)
        if match:
            errors.append('tool_error: ' + text[match.start():text.find('\n', match.start()) if '\n' in text[match.start():] else len(text)][:500])
    records = []
    reports = []
    for output in stage['outputs']:
        path = within(work, output['path'])
        if not path.exists():
            errors.append('output_missing: ' + output['path'])
            continue
        identity_tree = tree(path)
        if output.get('nonempty', True) and (not identity_tree['entries'] or not any(
                v.get('size', 0) > 0 for v in identity_tree['entries'].values())):
            errors.append('output_empty: ' + output['path'])
        if stamp(path) == outputs[output['path']]:
            errors.append('output_stale: ' + output['path'])
        records.append(dict(output, tree=identity_tree))
        if output.get('kind') == 'report':
            reports.append(path)
    qor, audits = audit_reports(runtime, reports)
    for audit in audits:
        if audit['skipped_files'] or not audit['files']:
            errors.append('report_not_audited')
        for finding in audit['findings']:
            if finding['code'] in BLOCKING_FINDINGS:
                errors.append('report_finding: ' + finding['code'])
    readiness = {'status': 'insufficient', 'reason': 'normalized_qor_manifest_not_provided',
                 'audits': audits, 'manifest': None}
    validity = 'invalid' if errors else 'valid'
    if stage.get('qor_manifest'):
        path = within(work, stage['qor_manifest'])
        try:
            manifest = load(path)
            issues = qor.validate(manifest)
            for evidence in manifest['evidence']:
                evidence_path = within(work, evidence['path'])
                if not evidence_path.is_file() or sha(evidence_path) != evidence['sha256']:
                    issues.append('evidence_missing_or_hash_mismatch')
            readiness.update(status='valid' if not issues else 'invalid', reason=issues, manifest=manifest)
            if issues:
                errors.append('qor_manifest_invalid: ' + ','.join(issues))
                validity = 'invalid'
        except (ValueError, OSError, KeyError, TypeError, RequestError) as error:
            readiness.update(status='insufficient', reason=str(error))
            if not errors:
                validity = 'insufficient'
    return {'status': validity, 'reasons': errors, 'outputs': records, 'qor': readiness}


def run_process(run, state, argv, cwd, environment, logfile, timeout_seconds, deadline, memory_limit):
    attempt = run / 'attempts' / str(state['attempt'])
    logfile.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    peak = 0
    reason = None
    with logfile.open('wb') as stream:
        process = subprocess.Popen(argv, cwd=str(cwd), env=environment, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
        token = identity(process.pid)
        state['tool_process'] = token
        state_save(run, state)
        while process.poll() is None:
            elapsed = time.monotonic() - start
            if (attempt / 'cancel.json').exists():
                reason = 'cancelled'
            elif elapsed >= timeout_seconds or time.monotonic() >= deadline:
                reason = 'timed_out'
            peak = max(peak, group_rss(token))
            if memory_limit is not None and peak > memory_limit * 1024 ** 3:
                reason = 'memory_limit_exceeded'
            if reason:
                stop_group(token)
                break
            time.sleep(0.1)
        returncode = process.wait()
        if group_members(token):
            stop_group(token)
            reason = reason or 'lingering_process_group'
    state['tool_process'] = None
    state_save(run, state)
    return {'exit_code': returncode, 'reason': reason, 'wall_seconds': round(time.monotonic() - start, 3),
            'peak_group_rss_bytes': peak, 'argv': argv, 'cwd': str(cwd), 'log': str(logfile)}


def make_work(run, destination, request, checkpoint=None):
    verify_inputs(run, request)
    shutil.copytree(str(run / 'inputs'), str(destination))
    if checkpoint:
        for item in checkpoint['paths']:
            source = Path(checkpoint['directory']) / item['path']
            if tree(source) != item['tree']:
                raise RequestError('Checkpoint fingerprint changed: ' + item['path'])
            copy_path(source, within(destination, item['path']))


def verify_inputs(run, request):
    for item in request['input_identity']['inputs']:
        if tree(within(run / 'inputs', item['destination'])) != item['tree']:
            raise RequestError('Captured input fingerprint changed: ' + item['destination'])


def verify_checkpoint(run, state, stage, work, request, environment, deadline):
    spec = stage['checkpoint']
    attempt = run / 'attempts' / str(state['attempt'])
    directory = attempt / 'checkpoints' / stage['id']
    directory.mkdir(parents=True)
    paths = []
    for name in spec['paths']:
        source = within(work, name)
        copy_path(source, within(directory, name))
        paths.append({'path': name, 'tree': tree(source)})
    checkpoint = {'stage': stage['id'], 'directory': str(directory), 'paths': paths, 'verified': False}
    probe_work = attempt / 'restore-probes' / stage['id']
    probe_work.parent.mkdir(exist_ok=True)
    make_work(run, probe_work, request, checkpoint)
    probe = spec['restore_probe']
    profile = request['profile']
    probe_env = dict(environment, EDA_RUN_DIR=str(probe_work))
    result = run_process(run, state, command(probe['argv'], profile, probe_work), probe_work,
        probe_env, attempt / 'logs' / (stage['id'] + '.restore.log'), probe['timeout_seconds'],
        deadline, profile.get('resources', {}).get('memory_limit_gib'))
    text = Path(result['log']).read_text(errors='replace')
    passed = (result['exit_code'] == 0 and not result['reason'] and
              re.search(probe['success_pattern'], text, re.M) is not None and
              not any(re.search(p, text, re.M) for p in TOOL_ERRORS + probe.get('error_patterns', [])))
    checkpoint.update(verified=passed, probe=result)
    atomic(directory / 'checkpoint.json', checkpoint)
    return checkpoint


def snapshot_outputs(attempt, stage_id, work, validation):
    for output in validation.get('outputs', []):
        destination = within(attempt / 'artifacts' / stage_id, output['path'])
        copy_path(within(work, output['path']), destination)
        if tree(destination) != output['tree']:
            raise RequestError('Output changed during capture: ' + output['path'])
        output['snapshot'] = str(destination)


def worker(run, attempt_number):
    run = Path(run)
    with lock(run / '.control.lock'):
        state = load(run / 'state.json')
        if state['attempt'] != attempt_number or state['status'] != 'queued':
            return
    request = load(run / 'request.json')
    profile, flow = request['profile'], request['flow']
    attempt = run / 'attempts' / str(attempt_number)
    slot = (Path(profile['run_root']) / '.heavy-job.lock').open('a+')
    try:
        while True:
            if (attempt / 'cancel.json').exists():
                state.update(status='cancelled', reason='cancelled_while_queued')
                return
            try:
                fcntl.flock(slot.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.1)
        memory = available_memory()
        # A killed worker can leave its separately owned tool session alive.
        # The flock was released by the kernel, but that does not free the resource budget.
        for path in Path(profile['run_root']).glob('*/state.json'):
            if path.parent != run:
                other = load(path)
                if not alive(other.get('worker')) and group_members(other.get('tool_process')):
                    raise RequestError('Orphaned tool group occupies run_root; cancel run ' + other['run_id'])
        minimum = profile.get('resources', {}).get('min_free_memory_gib', 0)
        if minimum and (memory is None or memory < minimum):
            raise RequestError('Insufficient memory when acquiring execution slot')
        if input_identity(profile, flow) != request['input_identity']:
            raise RequestError('Inputs changed after submission; do not run a different design')
        deadline = time.monotonic() + flow['budget_seconds']
        work = attempt / 'work'
        make_work(run, work, request, state.get('resume_from'))
        environment = os.environ.copy()
        environment.update({k: str(v) for k, v in profile.get('env', {}).items()})
        environment.update(EDA_RUN_DIR=str(work), EDA_RUN_ID=state['run_id'],
                           EDA_ATTEMPT=str(attempt_number),
                           EDA_THREADS=str(profile.get('resources', {}).get('threads_per_job', 4)))
        state.update(status='running', started_at=now(), reason=None)
        state_save(run, state)
        event(run, 'running', attempt=attempt_number)
        for index in range(state['start_index'], len(flow['stages'])):
            stage = flow['stages'][index]
            if (attempt / 'cancel.json').exists():
                state.update(status='cancelled', reason='cancelled_before_stage')
                break
            if deadline - time.monotonic() < stage.get('minimum_start_seconds', 0.1):
                state.update(status='timed_out', reason='run_budget_exhausted')
                break
            state['current_stage'] = stage['id']
            state_save(run, state)
            event(run, 'stage_started', stage=stage['id'], attempt=attempt_number)
            outputs = {item['path']: stamp(within(work, item['path'])) for item in stage['outputs']}
            cwd = work if stage.get('cwd', '.') == '.' else within(work, stage['cwd'])
            result = run_process(run, state, command(stage['argv'], profile, work), cwd,
                dict(environment, EDA_STAGE=stage['id']), attempt / 'logs' / (stage['id'] + '.log'),
                stage['timeout_seconds'], deadline, profile.get('resources', {}).get('memory_limit_gib'))
            record = {'id': stage['id'], 'index': index, 'attempt': attempt_number, 'execution': result,
                      'execution_status': 'completed', 'validation': {'status': 'insufficient', 'reasons': []},
                      'checkpoint': None}
            state['stages'].append(record)
            if result['reason'] or result['exit_code'] != 0:
                execution_status = result['reason'] if result['reason'] in ('cancelled', 'timed_out') else 'failed'
                record['execution_status'] = execution_status
                state.update(status=execution_status, result_validity='insufficient',
                             reason=result['reason'] or 'tool_nonzero_exit')
                break
            record['validation'] = evaluate(stage, work, Path(result['log']), outputs, Path(request['runtime_dir']))
            snapshot_outputs(attempt, stage['id'], work, record['validation'])
            if record['validation']['status'] != 'valid':
                state.update(status='completed', result_validity=record['validation']['status'], reason='stage_validation_blocked')
                break
            if stage.get('checkpoint'):
                checkpoint = verify_checkpoint(run, state, stage, work, request, environment, deadline)
                record['checkpoint'] = checkpoint
                if not checkpoint['verified']:
                    state.update(status='completed', result_validity='invalid', reason='checkpoint_restore_failed')
                    if checkpoint['probe']['reason'] in ('cancelled', 'timed_out'):
                        state['status'] = checkpoint['probe']['reason']
                    break
            state_save(run, state)
            event(run, 'stage_completed', stage=stage['id'], attempt=attempt_number)
        else:
            if input_identity(profile, flow) != request['input_identity']:
                raise RequestError('Input identity changed during execution')
            state.update(status='completed', result_validity='valid', reason=None, pipeline_complete=True)
            state['qor_comparable'] = bool(state['stages'] and state['stages'][-1]['validation'].get('qor', {}).get('status') == 'valid')
    except BaseException as error:
        if group_members(state.get('tool_process')):
            stop_group(state['tool_process'])
        state.update(status='failed', result_validity='insufficient', reason='worker_error: ' + str(error), tool_process=None)
    finally:
        state['finished_at'] = now()
        state_save(run, state)
        event(run, 'attempt_finished', attempt=attempt_number, status=state['status'], reason=state.get('reason'))
        slot.close()


def resume(run, profile, optional_flow):
    with lock(run / '.control.lock'):
        state = state_read(run)
        request = load(run / 'request.json')
        flow = optional_flow or request['flow']
        if fingerprint(profile, flow) != request['fingerprint']:
            raise RequestError('Configuration changed; use a new run_id')
        if state['status'] in ACTIVE or group_members(state.get('tool_process')):
            raise RequestError('Task or owned tool group is still active; cannot resume')
        if state['status'] == 'completed' and state['result_validity'] == 'valid' and len(state['stages']) == len(flow['stages']):
            raise RequestError('Run is already complete')
        if input_identity(profile, flow) != request['input_identity']:
            raise RequestError('Input fingerprints changed; use a new run_id')
        verify_inputs(run, request)
        candidates = [s for s in state['stages'] if (s.get('checkpoint') or {}).get('verified')]
        checkpoint = candidates[-1]['checkpoint'] if candidates else None
        if checkpoint:
            for item in checkpoint['paths']:
                if tree(Path(checkpoint['directory']) / item['path']) != item['tree']:
                    raise RequestError('Checkpoint fingerprint changed; cannot resume')
        start_index = candidates[-1]['index'] + 1 if candidates else 0
        inherited = [s for s in state['stages'] if s['index'] < start_index]
        state.update(attempt=state['attempt'] + 1, status='queued', result_validity='insufficient',
                     reason=None, worker=None, tool_process=None, stages=inherited,
                     start_index=start_index, resume_from=checkpoint, qor_comparable=False)
        state['pipeline_complete'] = False
        for key in ('finished_at', 'started_at', 'current_stage', 'active_tool_detected'):
            state.pop(key, None)
        return launch(run, state, Path(request['runtime_dir']))


def collect(run, state, include_checkpoints, limit):
    number(limit, 'max_bytes', 1)
    if state['status'] in ACTIVE or group_members(state.get('tool_process')):
        raise RequestError('Collect a terminal task; use logs for an active task')
    paths = [run / 'state.json', run / 'request.json', run / 'events.jsonl']
    flow = load(run / 'request.json')['flow']
    for attempt in sorted((run / 'attempts').iterdir()):
        paths += [p for p in [attempt / 'state.json', attempt / 'worker.log'] if p.exists()]
        paths += list((attempt / 'logs').glob('*.log'))
        old = load(attempt / 'state.json')
        for stage in old.get('stages', []):
            if stage['attempt'] != int(attempt.name):
                continue
            for output in stage.get('validation', {}).get('outputs', []):
                if output.get('kind', 'artifact') == 'checkpoint' and not include_checkpoints:
                    continue
                source = within(attempt / 'artifacts' / stage['id'], output['path'])
                if tree(source) != output['tree']:
                    raise RequestError('Artifact changed after validation: ' + output['path'])
                paths += [source] if source.is_file() else [p for p in source.rglob('*') if p.is_file()]
            # Preserve declared diagnostic reports even if execution failed before validation.
            spec = flow['stages'][stage['index']]
            validated_paths = {o['path'] for o in stage.get('validation', {}).get('outputs', [])}
            for output in spec['outputs']:
                if output.get('kind') != 'report' or output['path'] in validated_paths:
                    continue
                source = within(attempt / 'work', output['path'])
                if source.exists():
                    tree(source)
                    paths += [source] if source.is_file() else [p for p in source.rglob('*') if p.is_file()]
        if include_checkpoints:
            paths += [p for p in (attempt / 'checkpoints').rglob('*') if p.is_file()]
    unique = sorted(set(p for p in paths if p.exists()))
    if sum(p.stat().st_size for p in unique) > limit:
        raise RequestError('Collection exceeds byte limit; use host-side artifact access or increase --max-bytes')
    inventory = []
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for p in unique:
            within(run, p.relative_to(run).as_posix())
            if p.is_symlink() or not p.is_file():
                raise RequestError('Only regular files can be collected')
            name = p.relative_to(run).as_posix()
            inventory.append({'path': name, 'size': p.stat().st_size, 'sha256': sha(p)})
            archive.add(str(p), arcname=name, recursive=False)
    return {'run_id': state['run_id'], 'files': inventory, 'archive_base64': base64.b64encode(data.getvalue()).decode('ascii')}


def monitor_metrics(token):
    members = group_members(token)
    cpu_seconds, rss = 0.0, 0
    for member in members:
        try:
            raw = Path('/proc/{}/stat'.format(member['pid'])).read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            cpu_seconds += (int(fields[11]) + int(fields[12])) / float(os.sysconf('SC_CLK_TCK'))
            for line in Path('/proc/{}/status'.format(member['pid'])).read_text().splitlines():
                if line.startswith('VmRSS:'):
                    rss += int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            continue
    return {'sample_time': time.time(), 'rss_bytes': rss if members else None,
            'cpu_seconds': cpu_seconds if members else None, 'process_count': len(members),
            'process_key': '{}:{}'.format(token['pid'], token['start_ticks']) if token and members else None}


def monitor_state(path):
    """Reconcile a view in memory only; monitoring must not rewrite worker state."""
    state = load(path)
    if state['status'] in ACTIVE and not alive(state.get('worker')):
        state.update(status='interrupted', result_validity='insufficient', pipeline_complete=False,
                     reason='worker_missing_or_host_restarted')
    return state


def monitor_summary(state):
    fields = ('run_id', 'attempt', 'status', 'current_stage', 'result_validity', 'pipeline_complete',
              'qor_comparable', 'created_at', 'started_at', 'finished_at', 'updated_at', 'reason')
    return {name: state.get(name) for name in fields}


def diagnostic_chunks(run, stages, cursors):
    chunks = []
    budget = 4 * 1024 * 1024
    for stage in stages:
        for kind in ('main', 'restore'):
            filename = stage['id'] + ('.restore.log' if kind == 'restore' else '.log')
            key = '{}/{}/{}/{}'.format(run.name, stage['attempt'], stage['id'], kind)
            chunk = {'key': key, 'stage': stage['id'], 'attempt': stage['attempt'], 'kind': kind,
                     'log': filename, 'available': False}
            chunks.append(chunk)
            path = within(run, 'attempts/{}/logs/{}'.format(stage['attempt'], filename))
            if not path.is_file():
                continue
            with path.open('rb') as stream:
                stat = os.fstat(stream.fileno())
                identity_key = '{}:{}'.format(stat.st_dev, stat.st_ino)
                cursor = cursors.get(key, {})
                offset = cursor.get('end_offset', 0)
                if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                    raise RequestError('Invalid diagnostic cursor')
                reset = cursor.get('identity') != identity_key or offset > stat.st_size
                if not reset and offset:
                    stream.seek(max(0, offset - 256))
                    anchor = hashlib.sha256(stream.read(min(offset, 256))).hexdigest()
                    reset = (anchor != cursor.get('anchor') or
                             (offset == stat.st_size and cursor.get('mtime_ns') != stat.st_mtime_ns))
                if reset:
                    offset = 0
                stream.seek(offset)
                data = stream.read(min(2 * 1024 * 1024, budget, max(0, stat.st_size - offset)))
                end = offset + len(data)
                stream.seek(max(0, end - 256))
                anchor = hashlib.sha256(stream.read(min(end, 256))).hexdigest()
            budget -= len(data)
            sealed = stage['execution_done'] if kind == 'main' else stage['status'] not in ('running', 'pending')
            chunk.update(available=True, identity=identity_key, size=stat.st_size, reset=reset,
                         start_offset=offset, end_offset=end, anchor=anchor, mtime_ns=stat.st_mtime_ns,
                         sealed=sealed, data_base64=base64.b64encode(data).decode('ascii'))
    return chunks


def monitor_snapshot(request):
    root = Path(request['profile']['run_root'])
    if not root.is_absolute():
        raise RequestError('run_root must be absolute')
    paths = sorted((p for p in root.glob('*/state.json') if not p.parent.is_symlink()),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    states, unreadable = [], 0
    for path in paths:
        try:
            identifier(path.parent.name)
            states.append(monitor_state(path))
        except (OSError, ValueError, KeyError, TypeError, RequestError):
            unreadable += 1
    states.sort(key=lambda s: (s['status'] in ACTIVE, s.get('created_at', '')), reverse=True)
    result = {'sampled_at': now(), 'runs': [monitor_summary(s) for s in states],
              'unreadable_runs': unreadable, 'run_limit': 200, 'selected': None,
              'host': {'cpu_count': os.cpu_count(), 'available_memory_gib': available_memory()}}
    run_id = request.get('run_id') or (states[0]['run_id'] if states else None)
    if not run_id:
        return result
    run = within(root, identifier(run_id))
    state = monitor_state(run / 'state.json')
    attempts = sorted(int(p.name) for p in (run / 'attempts').iterdir()
                      if p.name.isdigit() and not p.is_symlink() and (p / 'state.json').is_file())
    attempt = request.get('attempt') or state['attempt']
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt not in attempts:
        raise RequestError('Unknown attempt')
    if attempt != state['attempt']:
        state = load(run / 'attempts' / str(attempt) / 'state.json')
    saved = load(run / 'request.json')
    selected = monitor_summary(state)
    selected.update(attempts=attempts, stages=[], budget_seconds=saved['flow']['budget_seconds'],
                    resources=monitor_metrics(state.get('tool_process')))
    records = {s['id']: s for s in state.get('stages', [])}
    for spec in saved['flow']['stages']:
        record = records.get(spec['id'])
        item = {'id': spec['id'], 'tool': spec.get('tool', 'command'), 'status': 'pending',
                'attempt': attempt, 'wall_seconds': None, 'peak_rss_bytes': None,
                'checkpoint_verified': None, 'reasons': [], 'checks': {}, 'execution_done': bool(record)}
        if record:
            validation = record.get('validation', {})
            item.update(status=record['execution_status'], attempt=record['attempt'],
                        validity=validation.get('status'), reasons=validation.get('reasons', []),
                        wall_seconds=record['execution'].get('wall_seconds'),
                        exit_code=record['execution'].get('exit_code'),
                        peak_rss_bytes=record['execution'].get('peak_group_rss_bytes'),
                        checkpoint_verified=(record.get('checkpoint') or {}).get('verified'),
                        qor_status=validation.get('qor', {}).get('status'))
            observations = {}
            for audit in validation.get('qor', {}).get('audits', []):
                for report in audit.get('files', []):
                    for observation in report.get('observations', []):
                        metric = observation['metric']
                        if metric in ('drc_count', 'open_net_count'):
                            observations.setdefault(metric, []).append(dict(observation, report=Path(report['path']).name))
            for metric, evidence in observations.items():
                values = {e['value'] for e in evidence}
                item['checks'][metric] = {'value': next(iter(values)) if len(values) == 1 else None, 'evidence': evidence}
            if validation.get('status') == 'invalid' or item['checkpoint_verified'] is False:
                item['status'] = 'invalid'
            elif item['status'] == 'completed' and validation.get('status') != 'valid':
                item['status'] = 'insufficient'
        if spec['id'] == state.get('current_stage') and state['status'] == 'running':
            item['status'] = 'running'
        elif not record and state['status'] not in ACTIVE:
            item['status'] = 'not_run'
        selected['stages'].append(item)
    peaks = [s['peak_rss_bytes'] for s in selected['stages'] if s['peak_rss_bytes'] is not None and s['attempt'] == attempt]
    selected['peak_rss_bytes'] = max(peaks) if peaks else None
    if 'diagnostic_cursors' in request:
        selected['diagnostic_streams'] = diagnostic_chunks(run, selected['stages'], request['diagnostic_cursors'])
    log_attempt = request.get('log_attempt') or attempt
    if isinstance(log_attempt, bool) or not isinstance(log_attempt, int) or log_attempt not in attempts:
        raise RequestError('Unknown log attempt')
    selected['log_attempt'] = log_attempt
    directory = within(run, 'attempts/' + str(log_attempt))
    logs = {p.name: p for p in (directory / 'logs').glob('*.log') if p.is_file() and not p.is_symlink()}
    if (directory / 'worker.log').is_file():
        logs['@worker'] = directory / 'worker.log'
    selected['logs'] = sorted(logs)
    name = request.get('log')
    if name and name not in logs:
        raise RequestError('Unknown log')
    if not name:
        stage_log = str(state.get('current_stage')) + '.log'
        if state['status'] not in ACTIVE and stage_log in logs and state.get('reason') != 'checkpoint_restore_failed':
            name = stage_log
        elif logs:
            name = max(logs, key=lambda key: logs[key].stat().st_mtime)
    selected['log'] = {'name': name, 'text': '', 'total_bytes': 0, 'tail_bytes': 65536,
                       'highlight_line': None, 'at_tail': request.get('log_offset') is None}
    if name:
        path = within(directory, logs[name].relative_to(directory).as_posix())
        with path.open('rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            target = request.get('log_offset')
            if target is not None and (isinstance(target, bool) or not isinstance(target, int) or target < 0 or target > size):
                raise RequestError('Invalid log offset')
            offset = max(0, target - 16384) if target is not None else max(0, size - 65536)
            stream.seek(offset)
            data = stream.read(65536)
        if offset and b'\n' in data:
            first, data = data.split(b'\n', 1)
            offset += len(first) + 1
        highlight = data[:target - offset].count(b'\n') if target is not None and offset <= target < offset + len(data) else None
        selected['log'].update(text=data.decode('utf-8', errors='replace'), total_bytes=size,
                               window_offset=offset, highlight_line=highlight)
    result['selected'] = selected
    return result


def dispatch(request):
    if sys.platform != 'linux':
        raise RequestError('Execution endpoint must run on Linux')
    action, profile = request['action'], request['profile']
    if action == 'monitor':
        return monitor_snapshot(request)
    if action == 'preflight':
        return preflight(profile, request['flow'])
    if action == 'submit':
        return submit(profile, request['flow'], request['run_id'], request['_sources'])
    run = Path(profile['run_root']) / identifier(request['run_id'])
    if not (run / 'state.json').is_file():
        raise RequestError('Unknown run_id')
    if action == 'resume':
        return resume(run, profile, request.get('flow'))
    with lock(run / '.control.lock'):
        state = state_read(run)
        if action == 'status':
            return state
        if action == 'cancel':
            if state['status'] in ACTIVE:
                atomic(run / 'attempts' / str(state['attempt']) / 'cancel.json', {'requested_at': now()})
                return dict(state, cancellation_requested=True)
            if group_members(state.get('tool_process')):
                stop_group(state['tool_process'])
                state.update(status='cancelled', reason='orphaned_owned_tool_cancelled', tool_process=None)
                state_save(run, state)
            return dict(state, cancellation_requested=False)
        if action == 'logs':
            stage = request.get('stage') or state.get('current_stage')
            attempt_number = request.get('attempt') or state['attempt']
            if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
                raise RequestError('attempt must be a positive integer')
            attempt = run / 'attempts' / str(attempt_number)
            p = attempt / 'logs' / (identifier(stage) + '.log') if stage else attempt / 'worker.log'
            offset = max(0, int(request.get('offset', 0)))
            limit = max(1, min(int(request.get('limit', 65536)), 1024 * 1024))
            if not p.exists():
                return {'run_id': state['run_id'], 'offset': offset, 'next_offset': offset, 'text': '', 'eof': True}
            with p.open('rb') as stream:
                stream.seek(offset)
                data = stream.read(limit)
                end = stream.tell()
            return {'run_id': state['run_id'], 'offset': offset, 'next_offset': end,
                    'text': data.decode('utf-8', errors='replace'), 'eof': end >= p.stat().st_size}
        if action == 'collect':
            return collect(run, state, request.get('checkpoints', False), request.get('max_bytes', 64 * 1024 * 1024))
    raise RequestError('Unknown action')


def rpc(request):
    try:
        result = dispatch(request)
        ready = not (request['action'] == 'preflight' and not result['ready'])
        return {'ok': ready, 'command': request['action'], 'result': result}
    except (RequestError, OSError, ValueError, KeyError, TypeError, AttributeError, re.error) as error:
        return {'ok': False, 'command': request.get('action'), 'error': {'code': 'request_error', 'message': str(error)}}


if __name__ == '__main__':
    if 'REQUEST' in globals():
        print(json.dumps(rpc(REQUEST), ensure_ascii=False, allow_nan=False))
    elif len(sys.argv) > 1 and sys.argv[1] == '_worker':
        worker(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        print(json.dumps(rpc(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
