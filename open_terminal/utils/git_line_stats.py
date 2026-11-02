"""Isolated stdlib worker for repository file counts; no cwd/module imports."""
import json
import os
import sys


def main():
    # Count untracked files in one bounded worker under the terminal user's identity.
    counts = {}
    for path in json.load(sys.stdin):
        try:
            if os.path.islink(path):
                data = os.readlink(path).encode()
                counts[path] = data.count(b"\n") + int(bool(data) and not data.endswith(b"\n"))
                continue
            count, last, binary = 0, b"", False
            with open(path, "rb") as source:
                while chunk := source.read(65536):
                    if b"\0" in chunk:
                        binary = True
                        break
                    count += chunk.count(b"\n")
                    last = chunk[-1:]
            counts[path] = None if binary else count + int(bool(last) and last != b"\n")
        except OSError:
            counts[path] = None
    json.dump(counts, sys.stdout)


if __name__ == "__main__":
    main()
