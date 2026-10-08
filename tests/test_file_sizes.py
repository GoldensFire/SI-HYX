"""Regression checks for the source-size warning used in CI."""
from tools.check_file_sizes import WARN_LINES, long_files, main, source_files


def test_warning_starts_above_the_threshold_and_counts_the_last_line(tmp_path):
    source = tmp_path / 'feature.py'
    source.write_bytes(b'pass\n' * (WARN_LINES - 1) + b'pass')
    assert long_files([source], tmp_path) == []
    source.write_bytes(source.read_bytes() + b'\npass')
    assert long_files([source], tmp_path) == [('feature.py', WARN_LINES + 1)]


def test_long_lines_are_not_a_problem(tmp_path):
    source = tmp_path / 'feature.js'
    source.write_bytes(b'/' * 200_000)
    assert long_files([source], tmp_path) == []


def test_check_never_fails(monkeypatch, tmp_path):
    source = tmp_path / 'huge.py'
    source.write_bytes(b'pass\n' * (WARN_LINES + 10))
    monkeypatch.setattr('tools.check_file_sizes.source_files', lambda: [source])
    monkeypatch.setattr('tools.check_file_sizes.ROOT', tmp_path)
    assert main() == 0


def test_discovery_includes_new_nested_code_and_skips_builds(tmp_path):
    expected = []
    for relative in ('new_feature/deep/logic.py', 'frontend/view.tsx', 'tools/job.ps1',
                     'build/generated.py', '.claude/worktrees/old/main.py',
                     'node_modules/library/index.js', 'media/imported.py'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'')
        if relative.startswith(('new_feature/', 'frontend/', 'tools/')):
            expected.append(path)
    assert source_files(tmp_path) == sorted(expected)
