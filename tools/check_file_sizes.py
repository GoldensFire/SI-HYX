"""Limit maintained source files to 600 lines and 40 KiB, including new files."""
from pathlib import Path
import os

MAX_LINES = 600
MAX_BYTES = 40 * 1024
SOURCE_SUFFIXES = {
    '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
    '.css', '.qss', '.html', '.qml', '.sql', '.bat', '.cmd', '.ps1',
    '.sh', '.spec', '.c', '.h', '.cpp', '.hpp', '.cs', '.rs', '.go',
}
EXCLUDED_DIRS = {
    '.git', '.claude', '.wrangler', '.venv', 'venv', '__pycache__',
    '.pytest_cache', 'node_modules', 'vendor', 'bin', 'build', 'dist',
    'models', 'media', 'packages', 'graphify-out',
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


def check_file_sizes(files, root=ROOT):
    problems = []
    root = Path(root).resolve()
    for filename in files:
        path = Path(filename)
        data = path.read_bytes()
        # Count physical lines, including comments/blanks and an unterminated tail.
        lines = len(data.splitlines())
        if lines <= MAX_LINES and len(data) <= MAX_BYTES:
            continue
        try:
            label = path.resolve().relative_to(root).as_posix()
        except ValueError:
            label = str(path)
        problems.append(f'{label}: {lines} lines, {len(data)} bytes '
                        f'(limits: {MAX_LINES} lines / {MAX_BYTES} bytes)')
    return problems


def main():
    files = source_files()
    problems = check_file_sizes(files)
    for problem in problems:
        print(problem)
    print(f'File sizes: {len(files)} files, {len(problems)} violations')
    return int(bool(problems))


if __name__ == '__main__':
    raise SystemExit(main())
