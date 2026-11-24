"""Aggregate grocery purchases by customer with PySpark."""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType


def aggregate_purchases(purchases: DataFrame) -> DataFrame:
    """Return one row per customer with spend and purchase metrics."""
    required = {"customer_id", "purchase_id", "item", "quantity", "unit_price"}
    missing = required.difference(purchases.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    valid = purchases.where(
        F.col("customer_id").isNotNull()
        & F.col("purchase_id").isNotNull()
        & F.col("quantity").isNotNull()
        & F.col("unit_price").isNotNull()
        & (F.col("quantity") > 0)
        & (F.col("unit_price") >= 0)
    )
    return (
        valid.withColumn("line_total", (F.col("quantity") * F.col("unit_price")).cast(DecimalType(12, 2)))
        .groupBy("customer_id")
        .agg(
            F.sum("line_total").cast(DecimalType(14, 2)).alias("total_spend"),
            F.countDistinct("purchase_id").alias("purchase_count"),
            F.sum("quantity").cast("long").alias("items_bought"),
        )
        .orderBy("customer_id")
    )


def main() -> None:
    spark = SparkSession.builder.appName("grocery-customer-aggregation").getOrCreate()
    try:
        purchases = spark.read.option("header", True).option("inferSchema", True).csv("/opt/spark/data/purchases.csv")
        aggregate_purchases(purchases).show(truncate=False)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
