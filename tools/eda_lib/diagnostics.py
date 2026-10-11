"""Incremental message counts, independent from physical validity and QoR."""
import base64
import copy
from collections import OrderedDict
import hashlib
import re

LEVELS = ('fatal', 'error', 'warning', 'info')
PREFIX = re.compile(r'^\s*(Fatal|Error|Warning|Information|Info)\s*(?::|\s*-\[([^\]]+)\])\s*(.*)', re.I)
UVM = re.compile(r'^\s*UVM_(FATAL|ERROR|WARNING|INFO)\s+(?!:)\S.*')
CODE = re.compile(r'\(([A-Z][A-Z0-9_]*-\d+)\)\s*$')


def message(line):
    match = PREFIX.match(line)
    if match:
        severity = match.group(1).lower()
        severity = 'info' if severity == 'information' else severity
        tail_code = CODE.search(line)
        return severity, match.group(2) or (tail_code.group(1) if tail_code else None)
    match = UVM.match(line)
    if match:
        return match.group(1).lower(), None
    if line.startswith('Traceback (most recent call last):'):
        return 'error', 'PYTHON-TRACEBACK'
    return None


class MessageStream:
    def __init__(self):
        self.cursor = {}
        self.counts = dict.fromkeys(LEVELS, 0)
        self.groups = OrderedDict()
        self.pending = b''
        self.line = 1
        self.line_offset = 0
        self.long_lines = 0
        self.line_truncated = False
        self.groups_truncated = False

    def consume(self, raw):
        text = raw.decode('utf-8', errors='replace').rstrip('\r')
        parsed = message(text)
        if not parsed:
            return
        severity, code = parsed
        self.counts[severity] += 1
        key = (severity, code or hashlib.sha256(text.strip().encode()).hexdigest())
        if key not in self.groups and len(self.groups) >= 200:
            self.groups_truncated = True
            key = (severity, '__overflow__')
            code = 'OTHER'
        group = self.groups.setdefault(key, {'severity': severity, 'code': code or '无消息代码',
                                            'count': 0, 'message': text.strip()[:1200], 'samples': []})
        group['count'] += 1
        if len(group['samples']) < 3:
            group['samples'].append({'line': self.line, 'offset': self.line_offset, 'text': text[:1200]})

    def feed(self, chunk):
        data = base64.b64decode(chunk['data_base64'])
        position = chunk['start_offset']
        parts = data.split(b'\n')
        for index, part in enumerate(parts):
            room = max(0, 65536 - len(self.pending))
            self.pending += part[:room]
            if len(part) > room:
                self.line_truncated = True
            position += len(part)
            if index < len(parts) - 1:
                self.consume(self.pending)
                self.long_lines += int(self.line_truncated)
                self.line_truncated = False
                self.pending = b''
                self.line += 1
                position += 1
                self.line_offset = position
        if chunk['sealed'] and chunk['end_offset'] == chunk['size'] and self.pending:
            self.consume(self.pending)
            self.long_lines += int(self.line_truncated)
            self.pending = b''
            self.line_truncated = False
            self.line += 1
            self.line_offset = chunk['end_offset']
        self.cursor = {name: chunk[name] for name in ('identity', 'end_offset', 'anchor', 'mtime_ns')}

    def view(self, chunk):
        return {'available': True, 'counts': dict(self.counts), 'groups': copy.deepcopy(list(self.groups.values())),
                'complete': chunk['end_offset'] == chunk['size'] and not self.pending,
                'bytes_scanned': chunk['end_offset'], 'bytes_total': chunk['size'],
                'partial_line_pending': bool(self.pending), 'groups_truncated': self.groups_truncated,
                'long_lines': self.long_lines, 'attempt': chunk['attempt'], 'log': chunk['log']}


class DiagnosticStore:
    def __init__(self):
        self.streams = OrderedDict()

    def cursors(self):
        return {key: stream.cursor for key, stream in self.streams.items()}

    def update(self, selected):
        views = {}
        for chunk in selected.pop('diagnostic_streams', []):
            key = chunk['key']
            if not chunk['available']:
                self.streams.pop(key, None)
                views[(chunk['stage'], chunk['kind'])] = {'available': False, 'counts': None,
                                                         'complete': False, 'groups': []}
                continue
            stream = self.streams.get(key)
            if (stream is None or chunk['reset'] or stream.cursor.get('end_offset', 0) != chunk['start_offset']):
                stream = MessageStream()
                self.streams[key] = stream
            stream.feed(chunk)
            views[(chunk['stage'], chunk['kind'])] = stream.view(chunk)
            self.streams.move_to_end(key)
        while len(self.streams) > 256:
            self.streams.popitem(last=False)
        totals = dict.fromkeys(LEVELS, 0)
        observed, complete, groups = 0, True, []
        for stage in selected.get('stages', []):
            stage['diagnostics'] = {kind: views.get((stage['id'], kind),
                {'available': False, 'counts': None, 'complete': False, 'groups': []}) for kind in ('main', 'restore')}
            main = stage['diagnostics']['main']
            if main['available']:
                observed += 1
                for level in LEVELS:
                    totals[level] += main['counts'][level]
                complete = complete and main['complete']
            elif stage['status'] not in ('pending', 'not_run'):
                complete = False
            for kind, view in stage['diagnostics'].items():
                for group in view['groups']:
                    groups.append(dict(group, stage=stage['id'], kind=kind,
                                       attempt=view['attempt'], log=view['log']))
        selected['diagnostics'] = {'counts': totals if observed else None, 'complete': complete and observed > 0,
                                   'observed_stages': observed, 'groups': groups,
                                   'groups_truncated': any(v.get('groups_truncated') for v in views.values()),
                                   'scope': 'main logs on selected flow lineage; restore logs separate'}
