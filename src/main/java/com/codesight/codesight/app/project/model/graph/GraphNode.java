package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;

/**
 * One row per (snapshot, source file). Only populated for materialized snapshots
 * (first N per project per retention policy). Older snapshots are demoted to
 * a compressed bytea blob on GraphSnapshot and these rows are deleted.
 */
@Entity
@Table(
    name = "graph_node",
    indexes = {
        @Index(name = "idx_graph_node_snapshot_cluster", columnList = "snapshot_id, cluster_id"),
        @Index(name = "idx_graph_node_snapshot_path", columnList = "snapshot_id, file_path")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GraphNode {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "snapshot_id", nullable = false)
    private java.util.UUID snapshotId;

    @Column(name = "file_path", nullable = false, length = 1024)
    private String filePath;

    @Column(name = "cluster_id", nullable = false, length = 128)
    private String clusterId;

    @Column(name = "in_degree")
    private Integer inDegree;

    @Column(name = "out_degree")
    private Integer outDegree;

    @Column(name = "is_entry_point", nullable = false)
    @Builder.Default
    private Boolean isEntryPoint = false;

    @Column(name = "is_sink", nullable = false)
    @Builder.Default
    private Boolean isSink = false;
}
