#!/usr/bin/env python3
"""Remove the unused shaded JLine Telnet module from Hadoop's runtime JAR."""

import os
import sys
import tempfile
import zipfile
from pathlib import Path


CLASS_PREFIX = "org/apache/hadoop/shaded/org/jline/builtins/telnet/"
MAVEN_PREFIX = "META-INF/maven/org.jline/jline-remote-telnet/"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: remove_shaded_jline_telnet.py HADOOP_RUNTIME_JAR")

    jar_path = Path(sys.argv[1])
    temp_path = None
    try:
        with zipfile.ZipFile(jar_path, "r") as source:
            names = source.namelist()
            matches = [
                name
                for name in names
                if name.startswith(CLASS_PREFIX) or name.startswith(MAVEN_PREFIX)
            ]
            if not any(name.startswith(CLASS_PREFIX) for name in matches):
                raise RuntimeError(f"No shaded JLine Telnet classes found in {jar_path}")
            if not any(name.startswith(MAVEN_PREFIX) for name in matches):
                raise RuntimeError(f"No JLine Telnet Maven metadata found in {jar_path}")

            with tempfile.NamedTemporaryFile(
                dir=jar_path.parent, prefix=f"{jar_path.name}.", suffix=".tmp", delete=False
            ) as temp_file:
                temp_path = Path(temp_file.name)

            with zipfile.ZipFile(temp_path, "w") as destination:
                for entry in source.infolist():
                    if entry.filename.startswith(CLASS_PREFIX) or entry.filename.startswith(
                        MAVEN_PREFIX
                    ):
                        continue
                    destination.writestr(entry, source.read(entry.filename))

        with zipfile.ZipFile(temp_path, "r") as result:
            corrupt_entry = result.testzip()
            if corrupt_entry is not None:
                raise RuntimeError(f"Corrupt JAR entry after rewrite: {corrupt_entry}")
            remaining = [
                name
                for name in result.namelist()
                if name.startswith(CLASS_PREFIX) or name.startswith(MAVEN_PREFIX)
            ]
            if remaining:
                raise RuntimeError(f"JLine Telnet entries remain: {remaining}")

        os.replace(temp_path, jar_path)
        temp_path = None
        print(f"Removed {len(matches)} shaded JLine Telnet entries from {jar_path}")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
