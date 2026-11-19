"""Validate upstream CLI arguments without loading WinDivert or changing traffic."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from byerkn.core import DEFAULTS, Storage, profile_args

root = Path(__file__).resolve().parents[1]
results = []
with tempfile.TemporaryDirectory(prefix='byerkn-tests-cli-', dir=root) as tmp:
    storage = Storage(root, Path(tmp) / 'data')
    env = os.environ.copy()
    # winws carries an admin manifest; --dry-run does not open its driver.
    # Keep this validation process unprivileged, never use this for actual start.
    env['__COMPAT_LAYER'] = 'RunAsInvoker'
    for profile in storage.profiles():
        args = profile_args(profile, storage.current, storage.users, DEFAULTS)
        run = subprocess.run([str(storage.current / 'bin/winws.exe'), '--dry-run', *args],
                             cwd=storage.current / 'bin', capture_output=True, timeout=15,
                             creationflags=0x08000000, env=env)
        output = run.stdout.decode('utf-8', errors='replace') + run.stderr.decode('utf-8', errors='replace')
        results.append({'profile': profile.name, 'code': run.returncode, 'output': output})
        print(profile.name, run.returncode)
        if run.returncode:
            print(output[-1800:])
    (root / 'tests/cli-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
assert all(r['code'] == 0 for r in results), 'winws rejected one or more profiles'
print(f'{len(results)} upstream profiles accepted by winws --dry-run; driver not started.')
