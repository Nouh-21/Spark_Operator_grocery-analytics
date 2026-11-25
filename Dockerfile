# syntax=docker/dockerfile:1
# Spark 4.3.0 shades Jetty 12.1.8 into spark-core. Rebuild that shaded set
# with the current Jetty 12.1.15 release before creating the image.
FROM maven:3.9-eclipse-temurin-17 AS jetty-patch
WORKDIR /build
COPY docker/jetty-patch/pom.xml ./pom.xml
RUN mvn -B -ntp package

FROM maven:3.9-eclipse-temurin-17 AS java-patch
WORKDIR /build
COPY docker/java-patch/pom.xml ./pom.xml
RUN set -eu; \
    build_patch() { \
      name="$1"; common="$2"; thirdparty="$3"; shift 3; \
      mvn -B -ntp package -Dpatch.file="/patches/${name}.jar" \
        -Dguava.common="$common" -Dguava.thirdparty="$thirdparty" "$@"; \
    }; \
    mkdir /patches; \
    build_patch spark org.sparkproject.guava org.sparkproject.guava.thirdparty; \
    build_patch curator org.apache.curator.shaded.com.google.common org.apache.curator.shaded.com.google.thirdparty; \
    for relocation in \
      hadoop:org.apache.hadoop.shaded \
      hadoop-thirdparty:org.apache.hadoop.thirdparty \
      hadoop-curator:org.apache.hadoop.shaded.org.apache.curator.shaded; do \
      name=${relocation%%:*}; prefix=${relocation#*:}; \
      if [ "$name" = hadoop ]; then set -- -Phadoop-jackson; else set --; fi; \
      build_patch "$name" "${prefix}.com.google.common" "${prefix}.com.google.thirdparty" "$@"; \
    done

FROM apache/spark:4.3.0-python3 AS spark-runtime

USER root
WORKDIR /opt/spark

COPY --from=jetty-patch /build/target/jetty-patched-1.0.0.jar /tmp/jetty-patched.jar
COPY scripts/replace_shaded_jetty.py /tmp/replace_shaded_jetty.py
RUN python3 /tmp/replace_shaded_jetty.py \
      /opt/spark/jars/spark-core_2.13-4.3.0.jar \
      /tmp/jetty-patched.jar \
    && rm /tmp/jetty-patched.jar /tmp/replace_shaded_jetty.py

# Spark bundles these compression libraries in its runtime JARs. Replace the
# vulnerable copies so they cannot be loaded earlier on the classpath.
COPY scripts/download_maven_artifact.py /tmp/download_maven_artifact.py

ARG SNAPPY_JAVA_VERSION=1.1.10.9
RUN python3 /tmp/download_maven_artifact.py \
      "https://repo.maven.apache.org/maven2/org/xerial/snappy/snappy-java/${SNAPPY_JAVA_VERSION}/snappy-java-${SNAPPY_JAVA_VERSION}.jar" \
      /tmp/snappy-java.jar \
    && rm -f /opt/spark/jars/snappy-java-*.jar \
    && install -m 0644 /tmp/snappy-java.jar "/opt/spark/jars/snappy-java-${SNAPPY_JAVA_VERSION}.jar" \
    && rm /tmp/snappy-java.jar

# Spark 4.3.0 requires the newer LZ4 API (newBuilder). Version 1.11.4 keeps
# that API and includes the fix for CVE-2026-106451.
ARG LZ4_JAVA_VERSION=1.11.4
RUN python3 /tmp/download_maven_artifact.py \
      "https://repo.maven.apache.org/maven2/at/yawk/lz4/lz4-java/${LZ4_JAVA_VERSION}/lz4-java-${LZ4_JAVA_VERSION}.jar" \
      /tmp/lz4-java.jar \
    && rm -f /opt/spark/jars/lz4-java-*.jar \
    && install -m 0644 /tmp/lz4-java.jar "/opt/spark/jars/lz4-java-${LZ4_JAVA_VERSION}.jar" \
    && rm /tmp/lz4-java.jar

# Spark's Hive runtime includes libthrift 0.16.0; replace it with the fixed release.
ARG THRIFT_VERSION=0.24.0
RUN python3 /tmp/download_maven_artifact.py \
      "https://repo.maven.apache.org/maven2/org/apache/thrift/libthrift/${THRIFT_VERSION}/libthrift-${THRIFT_VERSION}.jar" \
      /tmp/libthrift.jar \
    && rm -f /opt/spark/jars/libthrift-*.jar \
    && install -m 0644 /tmp/libthrift.jar "/opt/spark/jars/libthrift-${THRIFT_VERSION}.jar" \
    && rm /tmp/libthrift.jar

# The image runs Java 21, so use Derby 10.17.1.0, which includes the
# DERBY-7147 LDAP injection fix (CVE-2022-46337).
ARG DERBY_VERSION=10.17.1.0
RUN set -eu; \
    for artifact in derby derbyshared derbytools; do \
      python3 /tmp/download_maven_artifact.py \
        "https://repo.maven.apache.org/maven2/org/apache/derby/${artifact}/${DERBY_VERSION}/${artifact}-${DERBY_VERSION}.jar" \
        "/tmp/${artifact}.jar"; \
    done; \
    rm -f /opt/spark/jars/derby-*.jar /opt/spark/jars/derbyshared-*.jar /opt/spark/jars/derbytools-*.jar; \
    for artifact in derby derbyshared derbytools; do \
      install -m 0644 "/tmp/${artifact}.jar" "/opt/spark/jars/${artifact}-${DERBY_VERSION}.jar"; \
    done; \
    rm /tmp/derby.jar /tmp/derbyshared.jar /tmp/derbytools.jar

# Hadoop 3.5.0 shades Jetty 9.4.58, which is EOL and cannot be updated from
# Maven Central. This batch job does not use Hadoop's embedded Jetty server.
COPY scripts/remove_shaded_hadoop_jetty.py /tmp/remove_shaded_hadoop_jetty.py
RUN python3 /tmp/remove_shaded_hadoop_jetty.py \
      /opt/spark/jars/hadoop-client-runtime-3.5.0.jar \
    && rm /tmp/remove_shaded_hadoop_jetty.py

# Hadoop also shades JLine built-ins; this batch app does not need them.
COPY scripts/remove_shaded_jline_builtins.py /tmp/remove_shaded_jline_builtins.py
RUN python3 /tmp/remove_shaded_jline_builtins.py \
      /opt/spark/jars/hadoop-client-runtime-*.jar \
      /opt/spark/jars/jline-3*.jar \
    && rm /tmp/remove_shaded_jline_builtins.py /tmp/download_maven_artifact.py

# Patch the Java classpath and omit the optional Spark Connect Scala REPL,
# which carries its own bundled Netty and Guava and is unused by the batch job.
RUN --mount=type=bind,from=java-patch,source=/patches,target=/patches \
    --mount=type=bind,source=scripts,target=/patch-scripts \
    python3 -B /patch-scripts/patch_java_runtime.py /opt/spark/jars /patches \
    && rm -rf /opt/spark/jars/connect-repl

# Keep only the Spark runtime payload. The upstream image also includes R,
# examples, sample datasets and tests, which this PySpark batch job does not use.
FROM eclipse-temurin:21-jre-noble AS runtime

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      bash gosu passwd procps python3 tini \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

RUN useradd --no-log-init --uid 185 --gid 0 --home-dir /opt/spark \
      --no-create-home --shell /usr/sbin/nologin spark \
    && mkdir -p /opt/spark/conf /opt/spark/work-dir \
    && chown -R 185:0 /opt/spark

COPY --from=spark-runtime --chown=185:0 /opt/spark/jars /opt/spark/jars
COPY --from=spark-runtime --chown=185:0 /opt/spark/python /opt/spark/python
COPY --from=spark-runtime --chown=185:0 /opt/spark/bin /opt/spark/bin
COPY --from=spark-runtime --chown=185:0 /opt/spark/sbin /opt/spark/sbin
COPY --from=spark-runtime /opt/spark/RELEASE /opt/spark/RELEASE
COPY --from=spark-runtime /opt/entrypoint.sh /opt/entrypoint.sh
COPY --chown=185:0 src/grocery_analytics /opt/spark/app/grocery_analytics
COPY --chown=185:0 data/purchases.csv /opt/spark/data/purchases.csv

ENV SPARK_HOME=/opt/spark \
    PYSPARK_PYTHON=python3 \
    PYSPARK_DRIVER_PYTHON=python3 \
    PYTHONPATH=/opt/spark/app \
    PATH=/opt/spark/bin:/opt/java/openjdk/bin:${PATH}

WORKDIR /opt/spark/work-dir
USER spark
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD ["bash"]
