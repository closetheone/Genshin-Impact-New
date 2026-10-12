"""Local-only maintenance access to submitted feedback."""
import argparse
import json
from pathlib import Path
import sqlite3

from archive_store import DEFAULT_DATABASE
from feedback_store import read_feedback


def main():
    parser = argparse.ArgumentParser(description='Read private local feedback; contact details are omitted by default.')
    parser.add_argument('--inbox', type=Path, default=DEFAULT_DATABASE.parent / 'feedback.sqlite3')
    parser.add_argument('--include-contact', action='store_true', help='Explicitly include private contact information')
    parser.add_argument('--resolve', metavar='ID', help='Mark an existing feedback item resolved')
    args = parser.parse_args()
    try:
        if args.resolve:
            with sqlite3.connect(args.inbox.resolve().as_uri() + '?mode=rw', uri=True) as connection:
                if connection.execute("UPDATE feedback SET status = 'resolved' WHERE id = ?", (args.resolve,)).rowcount != 1:
                    raise ValueError('Feedback ID does not exist.')
        print(json.dumps(read_feedback(args.inbox, args.include_contact), ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, 'Cannot read/update the private inbox; check its path and permissions.\n')


if __name__ == '__main__':
    main()
