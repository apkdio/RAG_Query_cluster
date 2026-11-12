"""兼容入口：聚类算法已移到 query_cluster.clustering.algorithm。"""

from .clustering.algorithm import OVERRIDE_SIM, THRESHOLD, cluster_terms, cohesion, similarity_matrix

__all__ = ["OVERRIDE_SIM", "THRESHOLD", "cluster_terms", "cohesion", "similarity_matrix"]
