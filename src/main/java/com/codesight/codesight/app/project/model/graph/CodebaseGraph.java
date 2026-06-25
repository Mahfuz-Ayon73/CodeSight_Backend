package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * One row per project. Holds the "current view" — pointer to the latest snapshot
 * plus a small JSON summary of clusters so ReactFlow can bootstrap the canvas
 * without scanning graph_node rows.
 */
@Entity
@Table(
    name = "codebase_graph",
    indexes = {
        @Index(name = "idx_codebase_graph_project", columnList = "project_id", unique = true)
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class CodebaseGraph {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "project_id", nullable = false, unique = true)
    private UUID projectId;

    /** Pointer to the latest snapshot. Null until first analysis completes. */
    @Column(name = "latest_snapshot_id")
    private UUID latestSnapshotId;

    /** Paradigm detected by the analyzer: WEB_FRAMEWORK_NEXTJS, WEB_API_NODEJS, PURE_LIBRARY_OR_PACKAGE, ... */
    @Column(length = 64)
    private String paradigm;

    @Column(name = "total_nodes")
    private Integer totalNodes;

    @Column(name = "total_edges")
    private Integer totalEdges;

    @Column(name = "total_clusters")
    private Integer totalClusters;

    /**
     * Compact per-cluster summary: [{cluster_id, title, summary, node_count}, ...]
     * Stored as JSONB in Postgres for fast read + future GIN indexing.
     */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "clusters_summary", columnDefinition = "jsonb")
    private String clustersSummary;

    /** Hash of the analyzer binary so the frontend can invalidate stale caches. */
    @Column(name = "generator_version", length = 64)
    private String generatorVersion;

    @Column(name = "generated_at")
    private LocalDateTime generatedAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        if (generatedAt == null) generatedAt = now;
        updatedAt = now;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
