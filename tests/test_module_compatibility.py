"""Public API guarantees across the extracted implementation modules."""
import os
import pickle
from pathlib import Path
import subprocess
import sys
import typing

import pytest


def test_dataclass_annotations_and_pickle_keep_public_types():
    import animepack
    hints = typing.get_type_hints(animepack.PackSettings)
    assert hints['users'] == list[animepack.UserList]
    settings = animepack.PackSettings()
    restored = pickle.loads(pickle.dumps(settings))
    assert type(restored) is animepack.PackSettings
    assert restored == settings


@pytest.mark.parametrize('entry, class_name', [
    ('main', 'UnifiedWindow'), ('edit_tab', 'EditTab'),
])
def test_spawn_entrypoint_uses_one_public_namespace(entry, class_name):
    # __mp_main__ loads the real file without entering its GUI event loop.
    code = '''
import runpy, sys
entry, class_name = sys.argv[1:]
namespace = runpy.run_path(entry + '.py', run_name='__mp_main__')
public = sys.modules[entry]
assert public is namespace['_api']
assert getattr(public, class_name) is namespace[class_name]
assert namespace['main'].__globals__['_api'] is public
assert getattr(public, class_name).__init__.__globals__['_api'] is public
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8')
    result = subprocess.run(
        [sys.executable, '-c', code, entry, class_name],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
