#!/usr/bin/env python3
"""Remove unused shaded JLine built-ins from Hadoop's runtime JAR."""

import os
import sys
import tempfile
import zipfile
from pathlib import Path


CLASS_PREFIX = "org/apache/hadoop/shaded/org/jline/builtins/"
MAVEN_PREFIXES = (
    "META-INF/maven/org.jline/jline-builtins/",
    "META-INF/maven/org.jline/jline-remote-telnet/",
)


def is_removed_entry(name: str) -> bool:
    return name.startswith(CLASS_PREFIX) or any(name.startswith(prefix) for prefix in MAVEN_PREFIXES)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: remove_shaded_jline_builtins.py HADOOP_RUNTIME_JAR")

    jar_path = Path(sys.argv[1])
    temp_path = None
    try:
        with zipfile.ZipFile(jar_path, "r") as source:
            entries = source.infolist()
            removed = [entry.filename for entry in entries if is_removed_entry(entry.filename)]
            if not any(name.startswith(CLASS_PREFIX) for name in removed):
                raise RuntimeError(f"No shaded JLine built-in classes found in {jar_path}")
            if not any(
                name.startswith("META-INF/maven/org.jline/jline-builtins/") for name in removed
            ):
                raise RuntimeError(f"No JLine built-ins Maven metadata found in {jar_path}")

            with tempfile.NamedTemporaryFile(
                dir=jar_path.parent, prefix=f"{jar_path.name}.", suffix=".tmp", delete=False
            ) as temp_file:
                temp_path = Path(temp_file.name)

            with zipfile.ZipFile(temp_path, "w") as destination:
                for entry in entries:
                    if not is_removed_entry(entry.filename):
                        destination.writestr(entry, source.read(entry.filename))

        with zipfile.ZipFile(temp_path, "r") as result:
            corrupt_entry = result.testzip()
            if corrupt_entry is not None:
                raise RuntimeError(f"Corrupt JAR entry after rewrite: {corrupt_entry}")
            remaining = [name for name in result.namelist() if is_removed_entry(name)]
            if remaining:
                raise RuntimeError(f"JLine built-in entries remain: {remaining}")

        os.replace(temp_path, jar_path)
        temp_path = None
        print(f"Removed {len(removed)} shaded JLine built-in entries from {jar_path}")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
