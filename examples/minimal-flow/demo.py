#!/usr/bin/env python3
"""Synthetic execution demo. This does not perform synthesis or estimate PPA."""
import json
import sys
from pathlib import Path

mode = sys.argv[1]
if mode == 'prepare':
    Path('demo_state.json').write_text(json.dumps({'synthetic_checkpoint': 1}))
    Path('prepare.rpt').write_text('Synthetic preparation completed. No EDA metrics.\n')
    print('DEMO_PREPARED')
elif mode in ('restore', 'analyze'):
    assert json.loads(Path('demo_state.json').read_text()) == {'synthetic_checkpoint': 1}
    if mode == 'analyze':
        Path('analysis.rpt').write_text('Synthetic checkpoint read successfully.\n')
    print('DEMO_RESTORED' if mode == 'restore' else 'DEMO_ANALYZED')
else:
    sys.exit('Unknown demo action')
