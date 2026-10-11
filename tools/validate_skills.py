#!/usr/bin/env python3
"""Validate this repository's candidate skill structure without installing it."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate():
    catalog = json.loads((ROOT / 'skills.json').read_text())
    if catalog.get('default_install') is not False:
        raise ValueError('Candidate skills must not install by default')
    listed = {entry['name'] for entry in catalog['skills']}
    actual = {p.name for p in (ROOT / 'skills').iterdir() if p.is_dir()}
    if listed != actual or len(listed) != len(catalog['skills']):
        raise ValueError('Skill catalog and directories differ')
    for entry in catalog['skills']:
        folder = ROOT / entry['path']
        if folder.resolve() != (ROOT / 'skills' / entry['name']).resolve():
            raise ValueError('Unexpected skill path: ' + entry['name'])
        if entry['status'] != 'candidate':
            raise ValueError('Change maturity status only with documented evaluation evidence')
        text = (folder / 'SKILL.md').read_text()
        front = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
        if not front:
            raise ValueError('Missing frontmatter: ' + entry['name'])
        fields = {}
        for line in front.group(1).splitlines():
            match = re.fullmatch(r'(name|description):\s*(.+)', line)
            if not match:
                raise ValueError('Use supported inline name/description fields: ' + entry['name'])
            if match.group(1) in fields:
                raise ValueError('Duplicate frontmatter field')
            fields[match.group(1)] = match.group(2).strip()
        name = fields.get('name', '')
        if name != entry['name'] or len(name) > 64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            raise ValueError('Invalid skill name: ' + name)
        desc = fields.get('description', '')
        if not desc or len(desc) > 1024 or '<' in desc or '>' in desc:
            raise ValueError('Invalid skill description: ' + name)
        if '[TODO:' in text:
            raise ValueError('Unfinished scaffold: ' + name)
        for document in folder.rglob('*.md'):
            for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
                if target.startswith(('https://', 'http://', '#')):
                    continue
                path = (document.parent / target.split('#', 1)[0]).resolve()
                try:
                    path.relative_to(ROOT)
                except ValueError:
                    raise ValueError('Reference escapes repository: ' + target)
                if not path.exists():
                    raise ValueError('Missing local reference: ' + target)
        metadata = folder / 'agents' / 'openai.yaml'
        if not metadata.is_file() or ('$' + name) not in metadata.read_text():
            raise ValueError('Missing invocation metadata: ' + name)
        for script in folder.rglob('*.py'):
            compile(script.read_text(), str(script), 'exec')
        print('PASS ' + name)
    print('Candidate skill structure and references validated; nothing installed.')


if __name__ == '__main__':
    validate()
