FROM apache/spark:3.5.7-python3

USER root
WORKDIR /opt/spark
COPY --chown=spark:root src/grocery_analytics /opt/spark/app/grocery_analytics
COPY --chown=spark:root data/purchases.csv /opt/spark/data/purchases.csv
ENV PYTHONPATH=/opt/spark/app
USER spark
