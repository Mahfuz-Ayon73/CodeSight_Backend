package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * One row per analysis run. The first N (per codesight.graph.retention.materialized-count)
 * are kept fully materialized with graph_node/graph_edge rows. Older snapshots
 * are demoted: graph_node/graph_edge deleted, full graph_blueprint.json stored
 * as a gzip-compressed bytea in compressed_map.
 */
@Entity
@Table(
    name = "graph_snapshot",
    indexes = {
        @Index(name = "idx_graph_snapshot_project_analyzed", columnList = "project_id, analyzed_at DESC"),
        @Index(name = "idx_graph_snapshot_commit", columnList = "project_id, commit_sha")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GraphSnapshot {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "project_id", nullable = false)
    private UUID projectId;

    /** Null for the very first analysis that runs on HEAD without a commit SHA. */
    @Column(name = "commit_sha", length = 64)
    private String commitSha;

    @Column(name = "commit_message", length = 1024)
    private String commitMessage;

    @Column(name = "commit_author", length = 256)
    private String commitAuthor;

    @Column(name = "committed_at")
    private LocalDateTime committedAt;

    @Column(name = "analyzed_at", nullable = false)
    private LocalDateTime analyzedAt;

    @Column(name = "nodes_count")
    private Integer nodesCount;

    @Column(name = "edges_count")
    private Integer edgesCount;

    @Column(name = "clusters_count")
    private Integer clustersCount;

    /** True for the first N snapshots per project, false for demoted blob-only snapshots. */
    @Column(name = "is_materialized", nullable = false)
    @Builder.Default
    private Boolean isMaterialized = true;

    /**
     * gzip(graph_blueprint.json). Populated when the snapshot is demoted from
     * materialized to blob-only. Null while the snapshot is materialized.
     */
    @Lob
    @Column(name = "compressed_map")
    private byte[] compressedMap;

    /**
     * Precomputed diff vs. the previous snapshot. Shape:
     * {
     *   "added_clusters": [...], "removed_clusters": [...],
     *   "added_nodes": [...], "removed_nodes": [...],
     *   "moved_nodes": [{"file":..., "from_cluster":..., "to_cluster":...}]
     * }
     */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "delta_json", columnDefinition = "jsonb")
    private String deltaJson;

    /** True while an analysis is writing this snapshot — used for re-entrancy guard. */
    @Column(name = "in_progress", nullable = false)
    @Builder.Default
    private Boolean inProgress = false;
}
