"""Allowlisted, reproducible skill ZIP and explicit non-overwriting installation."""
import argparse
from io import BytesIO
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'genshin-story-writer'
FILES = ('SKILL.md', 'agents/openai.yaml', 'references/script-formats.md', 'references/retrieval-contract.md',
         'scripts/archive_client.py', 'scripts/check_materials.py')


def skill_zip():
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in FILES:
            path = ROOT / 'skills' / NAME / filename
            if path.is_symlink():
                raise ValueError('Skill package does not allow symlinks.')
            info = zipfile.ZipInfo(f'{NAME}/{filename}', date_time=(2026, 10, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def install(destination):
    parent = Path(destination).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / NAME
    if target.exists() or target.is_symlink():
        raise FileExistsError('Destination skill already exists; no existing installation was overwritten.')
    with tempfile.TemporaryDirectory(prefix='.skill-install-', dir=parent) as temporary:
        staged = Path(temporary) / NAME
        with zipfile.ZipFile(BytesIO(skill_zip())) as archive:
            archive.extractall(temporary)
        # Recheck before moving; never merge a staged tree into an existing skill.
        if target.exists() or target.is_symlink():
            raise FileExistsError('Destination was created during installation.')
        staged.rename(target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path, help='Write ZIP to a new file')
    group.add_argument('--install-to', type=Path, help='Explicit skill parent directory; existing skills are never overwritten')
    args = parser.parse_args()
    try:
        if args.install_to:
            print(install(args.install_to))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('xb') as output:
                output.write(skill_zip())
            print(args.output.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
