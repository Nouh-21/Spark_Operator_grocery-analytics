from decimal import Decimal

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import DecimalType, IntegerType, StringType, StructField, StructType

from grocery_analytics.app import aggregate_purchases


@pytest.fixture(scope="session")
def spark():
    session = SparkSession.builder.master("local[2]").appName("grocery-aggregation-tests").config("spark.ui.enabled", "false").getOrCreate()
    yield session
    session.stop()


@pytest.fixture
def schema():
    return StructType([
        StructField("customer_id", StringType(), True),
        StructField("purchase_id", StringType(), True),
        StructField("item", StringType(), True),
        StructField("quantity", IntegerType(), True),
        StructField("unit_price", DecimalType(8, 2), True),
    ])


def test_aggregates_spend_purchases_and_quantities(spark, schema):
    purchases = spark.createDataFrame([
        ("C001", "P001", "Apples", 2, Decimal("1.50")),
        ("C001", "P001", "Bread", 1, Decimal("2.00")),
        ("C001", "P002", "Milk", 2, Decimal("1.25")),
        ("C002", "P003", "Rice", 1, Decimal("4.00")),
    ], schema)
    rows = aggregate_purchases(purchases).collect()
    assert [(r.customer_id, r.total_spend, r.purchase_count, r.items_bought) for r in rows] == [
        ("C001", Decimal("7.50"), 2, 5), ("C002", Decimal("4.00"), 1, 1)
    ]


def test_excludes_invalid_purchase_lines(spark, schema):
    purchases = spark.createDataFrame([
        ("C001", "P001", "Apples", 2, Decimal("1.50")),
        ("C001", "P002", "Invalid quantity", 0, Decimal("2.00")),
        ("C001", "P003", "Invalid price", 1, Decimal("-1.00")),
        (None, "P004", "Unknown customer", 1, Decimal("5.00")),
    ], schema)
    rows = aggregate_purchases(purchases).collect()
    assert len(rows) == 1
    assert rows[0].total_spend == Decimal("3.00")


def test_requires_expected_input_columns(spark):
    purchases = spark.createDataFrame([("C001",)], ["customer_id"])
    with pytest.raises(ValueError, match="Missing required columns"):
        aggregate_purchases(purchases)
