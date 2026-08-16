import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply an exact-match text replacement to a file, verifying uniqueness before writing."
    )
    parser.add_argument("file", help="path to the file to edit")
    parser.add_argument("--old", required=True, help="exact text to find")
    parser.add_argument("--new", required=True, help="replacement text")
    parser.add_argument(
        "--replace-all",
        action="store_true",
        help="replace every occurrence instead of failing on duplicates",
    )
    parser.add_argument(
        "--old-file",
        help="read --old from this file (for large/blocks of text, avoids shell quoting issues)",
    )
    parser.add_argument(
        "--new-file",
        help="read --new from this file",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: no such file: {path}", file=sys.stderr)
        return 1

    data = path.read_bytes()
    newline = b"\n"
    if b"\r\n" in data:
        newline = b"\r\n"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    if args.old_file:
        old = Path(args.old_file).read_text(encoding="utf-8")
    else:
        old = args.old
    if args.new_file:
        new = Path(args.new_file).read_text(encoding="utf-8")
    else:
        new = args.new

    count = text.count(old)
    if count == 0:
        print("ERROR: oldString not found", file=sys.stderr)
        return 2
    if count > 1 and not args.replace_all:
        print(f"ERROR: oldString found {count} times; use --replace-all or add more context", file=sys.stderr)
        return 3

    result = text.replace(old, new, -1 if args.replace_all else 1)
    if newline == b"\r\n":
        result = result.replace("\n", "\r\n")
    check = result.replace(new, old, -1 if args.replace_all else 1)
    if check != text:
        print("ERROR: round-trip verification failed; nothing written", file=sys.stderr)
        return 4

    path.write_bytes(result.encode("utf-8"))
    mode = "all" if args.replace_all else "1"
    print(f"OK: {mode} replacement applied to {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())