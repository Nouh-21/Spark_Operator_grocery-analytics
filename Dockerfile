# Spark 4.3.0 shades Jetty 12.1.8 into spark-core. Rebuild that shaded set
# with the current Jetty 12.1.15 release before creating the image.
FROM maven:3.9-eclipse-temurin-17 AS jetty-patch
WORKDIR /build
COPY docker/jetty-patch/pom.xml ./pom.xml
RUN mvn -B -ntp package

FROM apache/spark:4.3.0-python3

USER root
WORKDIR /opt/spark

# Bring the Ubuntu packages to their current security revisions instead of
# carrying the frozen OS package snapshot from the upstream Spark image.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

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

COPY --chown=spark:root src/grocery_analytics /opt/spark/app/grocery_analytics
COPY --chown=spark:root data/purchases.csv /opt/spark/data/purchases.csv
ENV PYTHONPATH=/opt/spark/app
USER spark
