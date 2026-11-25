# Grocery customer aggregation on Spark Kubernetes Operator

PySpark batch application that reads sample purchase lines, rejects invalid rows, and aggregates total spend, distinct purchases, and item quantities per customer. The result is printed by the Spark driver and can be inspected in its logs.

## Repository layout

- `src/grocery_analytics/app.py`: PySpark transformation and entry point.
- `tests/`: pytest coverage for aggregation, invalid rows, and input schema.
- `Dockerfile`: Spark 4.3.0 runtime image with the app, sample CSV, and maintained Jetty patched into Spark's shaded core JAR.
- `helm/grocery-analytics/`: Helm chart for the namespace, driver service account/RBAC, and Spark Operator resource.
- `argocd/application.yaml`: Argo CD Application configured for manual sync.
- `.github/workflows/ci-cd.yaml`: tests, image build and Trivy scan, Docker Hub publish, then GitOps tag update.

The Docker build upgrades Ubuntu packages before installing Spark dependencies. It patches Spark Core's relocated Jetty to 12.1.15, removes the unused, shaded Jetty 9 classes from Hadoop's `hadoop-client-runtime-3.5.0.jar`, updates Thrift to 0.24.0, and updates Derby to 10.17.1.0 for the Java 21 runtime. Removing Hadoop's embedded Jetty is specific to this batch image; Hadoop services that require it need a supported Hadoop/Jetty distribution instead.

## GitHub configuration

Configure these repository settings:

- Actions variable `DOCKERHUB_USERNAME`: `nouh23`.
- Actions secret `DOCKERHUB_TOKEN`: Docker Hub access token with permission to push `grocery-analytics`.
- Allow the workflow `contents: write` permission for the GitOps update job. Branch protection must allow its bot commit strategy.

The workflow runs pytest and builds the container for pull requests. Trivy blocks publication when it finds fixable HIGH/CRITICAL vulnerabilities. On a push to `main`, the scanned image is published with `latest`, `main`, `sha-<short>`, and full commit SHA tags. The SHA is written to `helm/grocery-analytics/values.yaml` so Argo CD deploys an immutable image reference. Pushing a Git tag such as `v1.2.0` publishes that version tag, `latest`, `sha-<short>`, and the full commit SHA. The bot's values commit does not trigger another image build.

## Cluster and Argo CD setup

1. Install Helm 3 and Kubeflow Spark Operator chart 2.4.0 with its `SparkApplication` CRD. The operator must watch the `spark-jobs` namespace used by this chart. Create that namespace before installing the operator, then configure its chart values as follows (the chart defaults to watching only `default`):

   ```yaml
   spark:
     jobNamespaces:
       - spark-jobs
     rbac:
       create: true
   ```

   Apply these values when installing/upgrading the operator (for example, with a values file passed to `helm upgrade --install`). The chart creates the operator RBAC for the configured job namespaces when `spark.rbac.create` is enabled.
2. Ensure cluster capacity for one 1-core/1 GiB driver and two 1-core/1 GiB executors.
3. Apply `argocd/application.yaml` once in the Argo CD namespace. It points to `Nouh-21/Spark_Operator_grocery-analytics`.
4. Ensure Argo CD can read the repository and access the destination cluster.
5. After an image is published, refresh the Argo CD application, review the image SHA, and click **Sync** when ready. Automated sync, prune, and self-heal are not configured.

The Docker Hub repository must be public for cluster pulls without an `imagePullSecret`. For a private repository, configure a registry pull secret for the Spark driver and executors.

Render the chart locally with `helm template grocery-analytics helm/grocery-analytics` before applying the Argo CD Application.

## Run tests locally

Use Java 17 and Python 3.11:

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q
```

The sample CSV is baked into the image at `/opt/spark/data/purchases.csv`. For real workloads, use cluster-accessible object storage or mounted persistent volumes for input and output.

## coderabbit review the code
