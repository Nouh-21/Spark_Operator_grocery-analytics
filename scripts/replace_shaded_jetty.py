#!/usr/bin/env python3
"""Replace Spark core's embedded, relocated Jetty modules with a patched set."""

import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path


JETTY_CLASSES = "org/sparkproject/jetty/"
JETTY_MAVEN_METADATA = "META-INF/maven/org.eclipse.jetty"
PATCHED_SECURITY_METADATA = (
    "META-INF/maven/org.eclipse.jetty/jetty-security/pom.properties"
)
JETTY_VERSION = b"12.1.15"


def is_old_jetty_entry(name: str) -> bool:
    return name.startswith(JETTY_CLASSES) or name.startswith(JETTY_MAVEN_METADATA)


def is_replaceable_patch_entry(name: str) -> bool:
    if name in {"META-INF/MANIFEST.MF", "META-INF/INDEX.LIST"}:
        return False
    upper_name = name.upper()
    return not upper_name.endswith((".SF", ".RSA", ".DSA", ".EC"))


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: replace_shaded_jetty.py SPARK_CORE_JAR PATCHED_JETTY_JAR")

    spark_jar, patched_jar = map(Path, sys.argv[1:])
    temp_path = None
    try:
        with zipfile.ZipFile(patched_jar) as patch:
            patch_entries = {
                entry.filename: (entry, patch.read(entry.filename))
                for entry in patch.infolist()
                if not entry.is_dir() and is_replaceable_patch_entry(entry.filename)
            }

        security_metadata = patch_entries.get(PATCHED_SECURITY_METADATA)
        if security_metadata is None or JETTY_VERSION not in security_metadata[1]:
            raise RuntimeError("The shaded patch does not identify jetty-security 12.1.15")
        if not any(name.startswith(JETTY_CLASSES) for name in patch_entries):
            raise RuntimeError("The shaded Jetty patch contains no relocated Jetty classes")

        with zipfile.ZipFile(spark_jar) as source:
            old_entries = source.infolist()
            if not any(entry.filename.startswith(JETTY_CLASSES) for entry in old_entries):
                raise RuntimeError(f"No embedded shaded Jetty classes found in {spark_jar}")

            with tempfile.NamedTemporaryFile(
                prefix=f"{spark_jar.stem}-", suffix=".jar", dir=spark_jar.parent, delete=False
            ) as temporary:
                temp_path = Path(temporary.name)

            with zipfile.ZipFile(temp_path, "w") as output:
                replaced = set()
                for entry in old_entries:
                    if is_old_jetty_entry(entry.filename):
                        continue
                    if entry.filename in patch_entries:
                        output.writestr(entry, patch_entries[entry.filename][1])
                        replaced.add(entry.filename)
                    else:
                        output.writestr(entry, source.read(entry.filename))
                for name, (entry, content) in patch_entries.items():
                    if name not in replaced:
                        output.writestr(entry, content)

        with zipfile.ZipFile(temp_path) as result:
            names = result.namelist()
            if PATCHED_SECURITY_METADATA not in names:
                raise RuntimeError("Patched jetty-security metadata is missing after replacement")
            if any(name.startswith(JETTY_MAVEN_METADATA) and b"12.1.8" in result.read(name)
                   for name in names if not name.endswith("/")):
                raise RuntimeError("Old Jetty 12.1.8 metadata remains in Spark core")

        os.chmod(temp_path, stat.S_IMODE(spark_jar.stat().st_mode))
        os.replace(temp_path, spark_jar)
        temp_path = None
        print(f"Replaced shaded Jetty in {spark_jar} with Jetty 12.1.15")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
