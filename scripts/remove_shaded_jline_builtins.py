#!/usr/bin/env python3
"""Remove unused JLine built-ins from Spark/Hadoop runtime JARs when present."""

import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path


CLASS_PREFIXES = (
    "org/apache/hadoop/shaded/org/jline/builtins/",
    "org/jline/builtins/",
)
MAVEN_PREFIXES = (
    "META-INF/maven/org.jline/jline-builtins/",
    "META-INF/maven/org.jline/jline-remote-telnet/",
    "META-INF/maven/org.jline/jline/",
)


def is_removed_entry(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in CLASS_PREFIXES + MAVEN_PREFIXES)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: remove_shaded_jline_builtins.py RUNTIME_JAR [RUNTIME_JAR ...]")

    for jar_path in map(Path, sys.argv[1:]):
        temp_path = None
        try:
            with zipfile.ZipFile(jar_path, "r") as source:
                entries = source.infolist()
                removed = [entry.filename for entry in entries if is_removed_entry(entry.filename)]
                class_entries = [name for name in removed if any(name.startswith(p) for p in CLASS_PREFIXES)]
                if not class_entries:
                    # Spark's standalone jline-3*.jar can contain only the
                    # core terminal APIs. The built-ins are shaded into
                    # hadoop-client-runtime on some Spark distributions, so
                    # process each matching JAR only when it actually has
                    # the classes being removed.
                    print(f"No JLine built-in classes found in {jar_path}; skipping")
                    continue

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

            os.chmod(temp_path, stat.S_IMODE(jar_path.stat().st_mode))
            os.replace(temp_path, jar_path)
            temp_path = None
            print(f"Removed {len(removed)} unused JLine entries from {jar_path}")
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
