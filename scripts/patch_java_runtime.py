#!/usr/bin/env python3
"""Update Spark's standalone JARs and replace the relocated bytecode in fat JARs."""

import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from download_maven_artifact import download


MAVEN = "https://repo.maven.apache.org/maven2"
GUAVA = "33.7.2-jre"
JACKSON = "2.21.7"
NETTY = "4.2.17.Final"
PARQUET_JACKSON = "1.18.2"
JACKSON_HADOOP = "org/apache/hadoop/shaded/com/fasterxml/jackson/"


def upgrade(jars, scratch, group, artifact, old, new, classifier=""):
    original = jars / f"{artifact}-{old}{classifier}.jar"
    if not original.is_file():
        raise RuntimeError(f"Expected runtime JAR is missing: {original}")
    filename = f"{artifact}-{new}{classifier}.jar"
    replacement = scratch / filename
    download(f"{MAVEN}/{group.replace('.', '/')}/{artifact}/{new}/{filename}", replacement)
    with ZipFile(replacement) as jar:
        if bad_entry := jar.testzip():
            raise RuntimeError(f"Invalid entry in {filename}: {bad_entry}")
    replacement.chmod(0o644)
    replacement.replace(jars / filename)
    original.unlink()


def owned_entries(guava, jackson):
    prefixes = (
        *guava,
        "META-INF/maven/com.google.guava/guava/",
        "META-INF/maven/com.google.guava/failureaccess/",
    )
    if jackson:
        prefixes += (
            JACKSON_HADOOP + "core/",
            JACKSON_HADOOP + "databind/",
            "META-INF/maven/com.fasterxml.jackson.core/jackson-core/",
            "META-INF/maven/com.fasterxml.jackson.core/jackson-databind/",
        )

    def owns(name):
        # Hadoop's old versioned Jackson entries can have unrelocated names.
        if match := re.match(r"META-INF/versions/\d+/(.*)", name):
            name = match[1]
            if jackson and name.startswith(("com/fasterxml/jackson/core/", "com/fasterxml/jackson/databind/")):
                return True
        return name.startswith(prefixes)

    return owns


def replace_shaded(target, scratch, patches, jackson=False):
    replacement = scratch / target.name
    with ZipFile(target) as source, ZipFile(replacement, "w") as result:
        patch_entries = {}
        ownership = []
        for patch, common, thirdparty in patches:
            owns = owned_entries((common, thirdparty), jackson)
            ownership.append(owns)
            with ZipFile(patch) as payload:
                for entry in payload.infolist():
                    if not entry.is_dir() and owns(entry.filename):
                        patch_entries[entry.filename] = (entry, payload.read(entry))
            for marker in (
                common + "base/Preconditions.class",
                thirdparty + "publicsuffix/PublicSuffixPatterns.class",
                *([JACKSON_HADOOP + "core/JsonFactory.class",
                   JACKSON_HADOOP + "databind/ObjectMapper.class"] if jackson else []),
            ):
                if marker not in source.namelist() or marker not in patch_entries:
                    raise RuntimeError(f"Expected relocated class missing: {marker} in {target} or {patch}")

        for entry in source.infolist():
            if not any(owns(entry.filename) for owns in ownership):
                result.writestr(entry, source.read(entry))
        for entry, content in patch_entries.values():
            result.writestr(entry, content)

    replacement.chmod(target.stat().st_mode & 0o777)
    os.replace(replacement, target)


def main(jars, patches):
    # Keep the temporary replacements on the same filesystem as the runtime JARs.
    with TemporaryDirectory(dir=jars) as directory:
        scratch = Path(directory)
        upgrade(jars, scratch, "com.google.guava", "guava", "33.6.0-jre", GUAVA)
        upgrade(jars, scratch, "org.apache.parquet", "parquet-jackson", "1.17.0", PARQUET_JACKSON)

        for group, module in (
            ("core", "core"),
            ("core", "databind"),
            ("dataformat", "dataformat-yaml"),
            ("datatype", "datatype-jsr310"),
            ("module", "module-scala_2.13"),
        ):
            upgrade(jars, scratch, f"com.fasterxml.jackson.{group}", f"jackson-{module}", "2.21.2", JACKSON)

        netty = sorted(jars.glob("netty-*-4.2.13.Final*.jar"))
        if not (jars / "netty-handler-4.2.13.Final.jar").is_file():
            raise RuntimeError("Expected Spark 4.3.0 Netty distribution not found")
        for jar in netty:
            artifact, classifier = jar.stem.split("-4.2.13.Final", 1)
            upgrade(jars, scratch, "io.netty", artifact, "4.2.13.Final", NETTY, classifier)

        replace_shaded(jars / "spark-network-common_2.13-4.3.0.jar", scratch, [
            (patches / "spark.jar", "org/sparkproject/guava/", "org/sparkproject/guava/thirdparty/"),
        ])
        replace_shaded(jars / "hadoop-client-runtime-3.5.0.jar", scratch, [
            (patches / f"{name}.jar", f"{prefix}/com/google/common/", f"{prefix}/com/google/thirdparty/")
            for name, prefix in (
                ("hadoop", "org/apache/hadoop/shaded"),
                ("hadoop-thirdparty", "org/apache/hadoop/thirdparty"),
                ("hadoop-curator", "org/apache/hadoop/shaded/org/apache/curator/shaded"),
            )
        ], jackson=True)
        replace_shaded(jars / "curator-client-5.9.0.jar", scratch, [
            (patches / "curator.jar", "org/apache/curator/shaded/com/google/common/",
             "org/apache/curator/shaded/com/google/thirdparty/"),
        ])


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))