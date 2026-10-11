#!/usr/bin/env python3
"""JSON CLI for explicitly requested local/SSH EDA runs. Standard library only."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ("import json,sys; request=json.load(sys.stdin); "
             "exec(compile(request['_sources']['runtime'],'<eda-runtime>','exec'),"
             "{'__name__':'__main__','REQUEST':request})")


class TransportError(Exception):
    pass


def transport_command(profile):
    config = profile.get('transport', {'type': 'local'})
    kind = config.get('type', 'local')
    python = config.get('python', sys.executable if kind == 'local' else '/usr/bin/python3')
    if not isinstance(python, str) or not python:
        raise ValueError('transport.python must be an executable path')
    if kind == 'local':
        return [python, '-c', BOOTSTRAP]
    if kind not in ('ssh', 'windows_ssh'):
        raise ValueError('transport.type must be local, ssh or windows_ssh')
    host = config.get('host')
    if not isinstance(host, str) or not host or host.startswith('-') or any(c.isspace() for c in host):
        raise ValueError('transport.host must be a single [user@]host')
    default = ['/mnt/c/Windows/System32/OpenSSH/ssh.exe'] if kind == 'windows_ssh' else ['ssh']
    executable = config.get('ssh_command', default)
    if not isinstance(executable, list) or not executable or any(not isinstance(x, str) for x in executable):
        raise ValueError('ssh_command must be an argv array')
    argv = executable + ['-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                         '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2']
    if config.get('port'):
        port = int(config['port'])
        if not 1 <= port <= 65535:
            raise ValueError('Invalid SSH port')
        argv += ['-p', str(port)]
    if config.get('identity_file'):
        argv += ['-i', config['identity_file']]
    return argv + [host, shlex.quote(python) + ' -c ' + shlex.quote(BOOTSTRAP)]


def call(request):
    request = dict(request)
    request['_sources'] = {
        'runtime': (ROOT / 'tools/eda_lib/runtime.py').read_text(),
        'qor': (ROOT / 'skills/eda-qor-experiments/scripts/qor.py').read_text()}
    timeout = float(request['profile'].get('transport', {}).get('request_timeout_seconds', 120))
    if not 0 < timeout <= 3600:
        raise ValueError('request_timeout_seconds must be > 0 and <= 3600')
    argv = transport_command(request['profile'])
    try:
        process = subprocess.run(argv, input=json.dumps(request, allow_nan=False).encode(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TransportError(str(error))
    if process.returncode != 0:
        raise TransportError('Transport exit {}: {}'.format(process.returncode,
                             process.stderr.decode(errors='replace')[-4000:]))
    try:
        response = json.loads(process.stdout.decode())
        if not isinstance(response, dict) or not isinstance(response.get('ok'), bool):
            raise ValueError('Missing response envelope')
    except (ValueError, UnicodeError) as error:
        raise TransportError('Invalid endpoint response: ' + str(error))
    return response


def extract_collection(result, output, max_bytes):
    """Verify an allowlisted archive before publishing a new local directory."""
    output = Path(output).absolute()
    if output.exists():
        raise ValueError('Collection destination already exists; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.eda-collect-', dir=str(output.parent)))
    try:
        inventory = {}
        for item in result['files']:
            name = item['path']
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or name in inventory or not path.parts:
                raise ValueError('Invalid/duplicate archive inventory path')
            if not isinstance(item['size'], int) or item['size'] < 0:
                raise ValueError('Invalid archive file size')
            inventory[name] = item
        if sum(i['size'] for i in inventory.values()) > max_bytes:
            raise ValueError('Collection exceeds byte limit')
        blob = base64.b64decode(result['archive_base64'], validate=True)
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
            for member in archive:
                item = inventory.get(member.name)
                if not member.isfile() or item is None or member.name in seen or member.size != item['size']:
                    raise ValueError('Archive does not match regular-file inventory')
                seen.add(member.name)
                target = temporary / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.extractfile(member) as source, target.open('xb') as destination:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(block)
                        destination.write(block)
                if digest.hexdigest() != item['sha256']:
                    raise ValueError('Collected file checksum mismatch: ' + member.name)
        if seen != set(inventory):
            raise ValueError('Archive omitted inventory files')
        os.rename(str(temporary), str(output))
    finally:
        if temporary.exists():
            shutil.rmtree(str(temporary))
    return {'run_id': result['run_id'], 'directory': str(output), 'files': result['files']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action')
    for name in ('preflight', 'submit', 'status', 'logs', 'collect', 'cancel', 'resume'):
        command = commands.add_parser(name)
        command.add_argument('--profile', required=True)
        if name in ('preflight', 'submit', 'resume'):
            command.add_argument('--flow', required=name != 'resume')
        if name != 'preflight':
            command.add_argument('--run-id', required=name != 'submit')
        if name == 'logs':
            command.add_argument('--stage')
            command.add_argument('--attempt', type=int)
            command.add_argument('--offset', type=int, default=0)
            command.add_argument('--limit', type=int, default=65536)
        if name == 'collect':
            command.add_argument('--out', required=True)
            command.add_argument('--checkpoints', action='store_true')
            command.add_argument('--max-bytes', type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    if not args.action:
        parser.error('a command is required')
    request = vars(args).copy()
    if args.action == 'submit' and not request.get('run_id'):
        request['run_id'] = 'run-' + uuid.uuid4().hex[:16]
    try:
        request['profile'] = json.loads(Path(args.profile).read_text())
        if request.get('flow'):
            request['flow'] = json.loads(Path(args.flow).read_text())
        response = call(request)
        if response['ok'] and args.action == 'collect':
            response['result'] = extract_collection(response['result'], args.out, args.max_bytes)
        code = 0 if response['ok'] else 2
    except TransportError as error:
        response = {'ok': False, 'command': args.action, 'run_id': request.get('run_id'),
                    'error': {'code': 'transport_uncertain', 'message': str(error),
                              'next_action': 'Query this run_id before retrying; remote state is unknown.'}}
        code = 3
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tarfile.TarError) as error:
        response = {'ok': False, 'command': args.action, 'run_id': request.get('run_id'),
                    'error': {'code': 'request_error', 'message': str(error)}}
        code = 2
    print(json.dumps(response, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
