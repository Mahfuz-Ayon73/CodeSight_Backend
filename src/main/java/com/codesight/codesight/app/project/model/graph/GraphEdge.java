package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;

/**
 * One row per (snapshot, source node, target node) edge.
 * For a 5000-node codebase expect ~15000 rows per materialized snapshot.
 */
@Entity
@Table(
    name = "graph_edge",
    indexes = {
        @Index(name = "idx_graph_edge_snapshot_source", columnList = "snapshot_id, source_node_id"),
        @Index(name = "idx_graph_edge_snapshot_target", columnList = "snapshot_id, target_node_id")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GraphEdge {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "snapshot_id", nullable = false)
    private java.util.UUID snapshotId;

    @Column(name = "source_node_id", nullable = false)
    private Long sourceNodeId;

    @Column(name = "target_node_id", nullable = false)
    private Long targetNodeId;

    /** Edge weight from the analyzer (import centrality, etc.). */
    @Column(name = "weight")
    private Double weight;
}
