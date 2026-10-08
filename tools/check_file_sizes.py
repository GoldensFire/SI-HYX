"""Warn about maintained source files longer than 1500 lines; never fails CI.

The number is a hint to look at cohesion, not a limit: a long file that holds
one coherent component is fine, a short file with unrelated code is not.
In GitHub Actions the warnings become ::warning annotations on the files.
"""
from pathlib import Path
import os

WARN_LINES = 1500
SOURCE_SUFFIXES = {
    '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
    '.css', '.qss', '.html', '.qml', '.sql', '.bat', '.cmd', '.ps1',
    '.sh', '.spec', '.c', '.h', '.cpp', '.hpp', '.cs', '.rs', '.go',
}
EXCLUDED_DIRS = {
    '.git', '.claude', '.wrangler', '.venv', 'venv', '__pycache__',
    '.pytest_cache', 'node_modules', 'vendor', 'bin', 'build', 'dist',
    'models', 'media', 'packages', 'artifacts', 'reports', 'tmp',
}
ROOT = Path(__file__).resolve().parents[1]


def source_files(root=ROOT):
    """Walk owned code, including untracked files; skip assets and dependencies."""
    paths = []
    for directory, subdirs, filenames in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in EXCLUDED_DIRS
                            and not d.startswith('.ab-av1-'))
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix.lower() in SOURCE_SUFFIXES:
                paths.append(path)
    return sorted(paths)


def long_files(files, root=ROOT):
    """(relative path, line count) for every file above WARN_LINES."""
    found = []
    root = Path(root).resolve()
    for filename in files:
        path = Path(filename)
        # Physical lines, including comments/blanks and an unterminated tail.
        lines = len(path.read_bytes().splitlines())
        if lines <= WARN_LINES:
            continue
        try:
            label = path.resolve().relative_to(root).as_posix()
        except ValueError:
            label = str(path)
        found.append((label, lines))
    return found


def warnings_text(found):
    in_actions = os.environ.get('GITHUB_ACTIONS') == 'true'
    out = []
    for label, lines in found:
        message = f'{lines} lines (> {WARN_LINES}): check whether the file still holds one component'
        out.append(f'::warning file={label}::{message}' if in_actions else f'{label}: {message}')
    return out


def main():
    files = source_files()
    found = long_files(files)
    for line in warnings_text(found):
        print(line)
    print(f'File sizes: {len(files)} files, {len(found)} above {WARN_LINES} lines (warning only)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
