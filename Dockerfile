FROM apache/spark:3.5.7-python3

USER root
WORKDIR /opt/spark

# Spark bundles snappy-java in its runtime JARs. Replace that transitive
# dependency so the vulnerable copy cannot be loaded earlier on the classpath.
ARG SNAPPY_JAVA_VERSION=1.1.10.9
ADD https://repo.maven.apache.org/maven2/org/xerial/snappy/snappy-java/${SNAPPY_JAVA_VERSION}/snappy-java-${SNAPPY_JAVA_VERSION}.jar /tmp/snappy-java.jar
RUN rm -f /opt/spark/jars/snappy-java-*.jar \
    && install -m 0644 /tmp/snappy-java.jar "/opt/spark/jars/snappy-java-${SNAPPY_JAVA_VERSION}.jar" \
    && rm /tmp/snappy-java.jar

COPY --chown=spark:root src/grocery_analytics /opt/spark/app/grocery_analytics
COPY --chown=spark:root data/purchases.csv /opt/spark/data/purchases.csv
ENV PYTHONPATH=/opt/spark/app
USER spark
