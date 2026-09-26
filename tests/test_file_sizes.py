"""Regression checks for the source-size guard used in CI."""
from tools.check_file_sizes import MAX_BYTES, MAX_LINES, check_file_sizes, source_files


def test_line_limit_includes_unterminated_last_line(tmp_path):
    source = tmp_path / 'feature.py'
    source.write_bytes(b'pass\n' * (MAX_LINES - 1) + b'pass')
    assert check_file_sizes([source], tmp_path) == []
    source.write_bytes(source.read_bytes() + b'\npass')
    assert len(check_file_sizes([source], tmp_path)) == 1


def test_long_lines_cannot_bypass_byte_limit(tmp_path):
    source = tmp_path / 'feature.js'
    source.write_bytes(b'/' * MAX_BYTES)
    assert check_file_sizes([source], tmp_path) == []
    source.write_bytes(b'/' * (MAX_BYTES + 1))
    assert len(check_file_sizes([source], tmp_path)) == 1


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
