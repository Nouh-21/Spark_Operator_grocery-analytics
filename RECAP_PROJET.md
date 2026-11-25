# Récapitulatif du projet Spark sur Kubernetes

## Objectif

Ce dépôt contient une application PySpark qui agrège des achats par client. Elle est empaquetée dans une image Docker, publiée sur Docker Hub par GitHub Actions, puis déployée sur Kubernetes avec le Kubeflow Spark Operator. Argo CD surveille le chart Helm dans le dépôt, mais conserve une synchronisation manuelle : l’application doit être explicitement synchronisée depuis Argo CD.

## Parcours de bout en bout

```text
Code PySpark + données CSV
        ↓
Tests pytest
        ↓
Construction de l’image Docker
        ↓
Scan Trivy (bloquant si vulnérabilités HIGH/CRITICAL)
        ↓
Publication sur Docker Hub avec tags liés au commit
        ↓
Mise à jour du tag SHA dans le chart Helm sur main
        ↓
Argo CD détecte l’état OutOfSync
        ↓
Synchronisation manuelle vers Kubernetes
        ↓
Spark Operator crée le driver et les executors Spark
```

## 1. Application PySpark

Le code se trouve dans `src/grocery_analytics/app.py`.

- La fonction `aggregate_purchases()` vérifie la présence des colonnes requises : `customer_id`, `purchase_id`, `item`, `quantity` et `unit_price`.
- Elle ignore les lignes sans client, achat, quantité ou prix, ainsi que les quantités non positives et les prix négatifs.
- Elle calcule le montant de chaque ligne, puis agrège par client : dépenses totales, nombre d’achats distincts et quantité totale d’articles.
- Le programme principal crée une SparkSession, lit `/opt/spark/data/purchases.csv`, affiche le résultat dans les logs du driver puis arrête Spark.

Les données d’exemple sont dans `data/purchases.csv`. Elles sont incluses dans l’image. En production, l’entrée devrait provenir d’un stockage accessible depuis le cluster, par exemple un stockage objet ou un volume monté.

Les tests de `tests/test_app.py` couvrent l’agrégation, le rejet de lignes invalides et la validation du schéma. Les dépendances de développement sont dans `requirements-dev.txt` : PySpark 4.3.0 et pytest 8.3.5.

## 2. Image Docker

Le `Dockerfile` part de `apache/spark:4.3.0-python3`, copie le code de l’application et le CSV dans `/opt/spark`, et configure le `PYTHONPATH` pour Spark. Spark 4.3.0 embarque Jetty 12.1.8 dans le JAR `spark-core`; une étape Maven reconstruit et relocalise les modules Jetty en 12.1.15, puis un script remplace les classes et métadonnées Jetty intégrées.

Avant la copie des dépendances, le Dockerfile exécute `apt-get update` et `apt-get upgrade` afin d’intégrer les révisions Ubuntu disponibles lors du build.

Le Dockerfile contient également des ajustements de dépendances Java du runtime Spark :

- il remplace `snappy-java` par la version 1.1.10.9 ;
- il remplace LZ4 par `at.yawk.lz4:lz4-java:1.11.4`, version compatible avec l’API de Spark 4.3.0 et corrigeant le finding CVE-2026-106451 ;
- il remplace `libthrift` 0.16.0 par la version 0.24.0 pour corriger CVE-2026-43871 ;
- il retire les classes et métadonnées des built-ins JLine intégrés dans Hadoop et dans le JAR JLine autonome de Spark 4.3.0. Cela enlève notamment le pager `Less` et le serveur Telnet concernés par les constats Trivy ; l’application batch n’utilise pas ces outils interactifs.
- il retire Jetty 9.4.58 relocalisé du JAR Hadoop `hadoop-client-runtime-3.5.0.jar`, ainsi que ses métadonnées Maven. Hadoop 3.5.0 l’embarque, et Jetty 9 est en fin de vie ; ce job batch n’utilise pas le serveur HTTP intégré à Hadoop. Ce choix ne convient pas à une image destinée à démarrer des services Hadoop qui dépendent de ce serveur.

Le téléchargement des deux JAR Maven passe par `scripts/download_maven_artifact.py`, qui retente les erreurs HTTP 429 et serveur avec temporisation. Le retrait des built-ins est réalisé par `scripts/remove_shaded_jline_builtins.py`, qui réécrit le JAR Hadoop et contrôle son intégrité.

Construction locale :

```bash
docker build -t grocery-analytics:local .
```

## 3. CI et publication avec GitHub Actions

Le pipeline est défini dans `.github/workflows/ci-cd.yaml`.

### Déclencheurs

- Une pull request qui touche les chemins surveillés lance les tests, la construction de l’image et Trivy.
- Un push sur `main` lance la CI, publie l’image si le scan réussit, puis met à jour le tag GitOps.
- Un tag Git commençant par `v` lance la CI et publie une image de version ; il ne met pas à jour le déploiement Argo CD.
- `workflow_dispatch` permet un lancement manuel.

### Jobs

1. **`test`** installe Java 17, Python 3.11 et les dépendances, puis exécute `PYTHONPATH=src pytest -q`.
2. **`build_scan`** construit une archive Docker, la charge dans le runner et la scanne avec Trivy. Le job échoue avec `exit-code: 1` si Trivy trouve des vulnérabilités HIGH ou CRITICAL. `ignore-unfixed: true` est activé.
3. **`publish`** s’exécute seulement hors pull request pour les pushes sur `main` et les tags `v*`. Il publie `docker.io/nouh23/grocery-analytics` sous des tags de branche/version et des tags SHA, dont le SHA complet.
4. **`update_gitops`** s’exécute seulement après un push sur `main`. Il inscrit le SHA complet dans `helm/grocery-analytics/values.yaml`, puis pousse le commit sur `main`.

Le job GitOps utilise le groupe de concurrence `gitops-main`, `queue: max` et `cancel-in-progress: false`. Il récupère `main` avant les tentatives, refuse de rétrograder vers un commit ancien, et réessaie le push jusqu’à cinq fois sans push forcé.

### Configuration GitHub nécessaire

- Variable Actions `DOCKERHUB_USERNAME` avec la valeur `nouh23`.
- Secret Actions `DOCKERHUB_TOKEN` contenant un token Docker Hub autorisé à pousser dans `grocery-analytics`.
- Permission `contents: write` accordée au job de mise à jour GitOps ; les règles de protection de `main` doivent permettre cette stratégie de commit par le bot.

## 4. Chart Helm et ressource Spark

Le chart se trouve dans `helm/grocery-analytics/`.

- `Chart.yaml` décrit le chart `grocery-analytics`.
- `values.yaml` fixe le namespace `spark-jobs`, le dépôt d’image `docker.io/nouh23/grocery-analytics` et son tag, ainsi que la configuration Spark.
- Les templates créent le namespace, le ServiceAccount `spark`, le Role et le RoleBinding du driver, puis la ressource `SparkApplication`.
- La ressource lance un job PySpark en mode `cluster` avec Spark 4.3.0, un driver de 1 cœur/1 Gio et deux executors de 1 cœur/1 Gio.
- Le fichier Python est référencé dans le conteneur via `local:///opt/spark/app/grocery_analytics/app.py`.

Rendu local du chart :

```bash
helm template grocery-analytics helm/grocery-analytics
```

Le Kubeflow Spark Operator doit être installé avec sa CRD `SparkApplication`, configuré pour surveiller le namespace `spark-jobs`, et disposer des droits RBAC nécessaires. Le chart de l’opérateur 2.4.0 surveille `default` par défaut ; sa configuration doit donc inclure `spark.jobNamespaces: [spark-jobs]` et activer la création de RBAC pour les jobs Spark. Le namespace cible doit exister avant l’installation de l’opérateur.

## 5. Argo CD et déploiement Kubernetes

`argocd/application.yaml` déclare une Application Argo CD qui :

- lit `https://github.com/Nouh-21/Spark_Operator_grocery-analytics.git` ;
- suit la branche `main` et le chemin `helm/grocery-analytics` ;
- déploie dans le namespace Kubernetes `spark-jobs`.

Aucune `syncPolicy` automatique n’est définie. Après publication, le commit GitOps change le tag d’image et Argo CD affiche l’application comme `OutOfSync`. Il faut examiner l’image SHA, puis déclencher **Sync** manuellement. Le Spark Operator prend alors en charge le cycle de vie de la `SparkApplication` et de ses pods driver/executor. Le résultat de l’agrégation peut être consulté dans les logs du driver.

Le dépôt Docker Hub doit être public, ou un `imagePullSecret` doit être configuré pour les pods Spark si le dépôt est privé.

## État actuel et points à reprendre

- L’image utilise Spark 4.3.0 et remplace le Jetty 12.1.8 intégré à `spark-core` par Jetty 12.1.15, relocalisé comme les classes Spark. Elle retire également le Jetty 9.4.58 relocalisé du JAR Hadoop, inutilisé par ce job batch.
- LZ4 est fixé en version 1.11.4, compatible avec l’API Spark 4 et incluant le correctif de CVE-2026-106451. Les composants JLine `Less` et Telnet inutilisés ont été retirés des JAR Hadoop et JLine autonomes ; les scans ciblés ne relèvent plus les CVE JLine concernées.
- Après mise à jour des paquets Ubuntu, le scan Trivy ne signale plus les anciennes versions d’`apt`, `libapt-pkg` et `linux-libc-dev`. Le scan complet doit être relancé après les derniers changements pour confirmer les findings Java restants.
- Une erreur `429` Maven Central a aussi été observée pendant un build. Le Dockerfile utilise désormais un téléchargeur avec nouvelles tentatives, et une reconstruction locale a réussi après ce changement.
- Des modifications locales sont encore en cours. La publication Docker Hub, la mise à jour GitOps distante et la synchronisation Argo CD restent à faire après validation de la CI et push des changements concernés.
