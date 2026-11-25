FROM apache/spark:3.5.7-python3

USER root
WORKDIR /opt/spark

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

ARG LZ4_JAVA_VERSION=1.8.1
RUN python3 /tmp/download_maven_artifact.py \
      "https://repo.maven.apache.org/maven2/at/yawk/lz4/lz4-java/${LZ4_JAVA_VERSION}/lz4-java-${LZ4_JAVA_VERSION}.jar" \
      /tmp/lz4-java.jar \
    && rm -f /opt/spark/jars/lz4-java-*.jar \
    && install -m 0644 /tmp/lz4-java.jar "/opt/spark/jars/lz4-java-${LZ4_JAVA_VERSION}.jar" \
    && rm /tmp/lz4-java.jar

# Hadoop shades JLine 3.9.0, including interactive built-ins, into
# hadoop-client-runtime. The batch app needs none of them; remove those classes
# and their Maven inventory entries, including the vulnerable Less pager.
COPY scripts/remove_shaded_jline_builtins.py /tmp/remove_shaded_jline_builtins.py
RUN python3 /tmp/remove_shaded_jline_builtins.py /opt/spark/jars/hadoop-client-runtime-*.jar \
    && rm /tmp/remove_shaded_jline_builtins.py /tmp/download_maven_artifact.py

COPY --chown=spark:root src/grocery_analytics /opt/spark/app/grocery_analytics
COPY --chown=spark:root data/purchases.csv /opt/spark/data/purchases.csv
ENV PYTHONPATH=/opt/spark/app
USER spark
