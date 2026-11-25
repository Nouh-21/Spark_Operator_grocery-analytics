#!/usr/bin/env python3
"""Remove Hadoop's unused, shaded Jetty 9 modules from its runtime JAR."""

import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path


JETTY_CLASS_MARKER = "/org/apache/hadoop/shaded/org/eclipse/jetty/"
JETTY_MAVEN_PREFIXES = (
    "META-INF/maven/org.eclipse.jetty/",
    "META-INF/maven/org.eclipse.jetty.websocket/",
)


def is_jetty_entry(name: str) -> bool:
    return (
        name.startswith("org/apache/hadoop/shaded/org/eclipse/jetty/")
        or JETTY_CLASS_MARKER in f"/{name}"
        or any(name.startswith(prefix) for prefix in JETTY_MAVEN_PREFIXES)
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: remove_shaded_hadoop_jetty.py HADOOP_RUNTIME_JAR")

    jar_path = Path(sys.argv[1])
    temp_path = None
    try:
        with zipfile.ZipFile(jar_path, "r") as source:
            entries = source.infolist()
            removed = [entry.filename for entry in entries if is_jetty_entry(entry.filename)]
            removed_classes = [name for name in removed if name.endswith(".class")]
            if not any(name.endswith("/http/HttpParser.class") for name in removed_classes):
                raise RuntimeError(f"Expected shaded Jetty HttpParser class not found in {jar_path}")

            with tempfile.NamedTemporaryFile(
                dir=jar_path.parent, prefix=f"{jar_path.name}.", suffix=".tmp", delete=False
            ) as temp_file:
                temp_path = Path(temp_file.name)

            with zipfile.ZipFile(temp_path, "w") as destination:
                for entry in entries:
                    if not is_jetty_entry(entry.filename):
                        destination.writestr(entry, source.read(entry.filename))

        with zipfile.ZipFile(temp_path, "r") as result:
            corrupt_entry = result.testzip()
            if corrupt_entry is not None:
                raise RuntimeError(f"Corrupt JAR entry after rewrite: {corrupt_entry}")
            remaining = [name for name in result.namelist() if is_jetty_entry(name)]
            if remaining:
                raise RuntimeError(f"Shaded Jetty entries remain: {remaining[:10]}")

        os.chmod(temp_path, stat.S_IMODE(jar_path.stat().st_mode))
        os.replace(temp_path, jar_path)
        temp_path = None
        print(f"Removed {len(removed_classes)} unused shaded Jetty classes from {jar_path}")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
