package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * A named, immutable-base overlay containing human edits to one analyzer snapshot.
 * The analyzer-owned graph is never mutated; selecting the original map simply skips
 * this overlay.
 */
@Entity
@Table(
    name = "graph_edit_revision",
    uniqueConstraints = @UniqueConstraint(
        name = "uq_graph_edit_revision_snapshot_number",
        columnNames = {"snapshot_id", "revision_number"}
    ),
    indexes = @Index(
        name = "idx_graph_edit_revision_project_snapshot",
        columnList = "project_id, snapshot_id"
    )
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GraphEditRevision {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Version
    private Long version;

    @Column(name = "project_id", nullable = false)
    private UUID projectId;

    @Column(name = "snapshot_id", nullable = false)
    private UUID snapshotId;

    @Column(name = "revision_number", nullable = false)
    private Integer revisionNumber;

    @Column(nullable = false, length = 160)
    private String name;

    @Column(length = 1000)
    private String description;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "added_edges_json", nullable = false, columnDefinition = "jsonb")
    @Builder.Default
    private String addedEdgesJson = "[]";

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "removed_edge_ids_json", nullable = false, columnDefinition = "jsonb")
    @Builder.Default
    private String removedEdgeIdsJson = "[]";

    @Column(name = "edited_by", nullable = false)
    private UUID editedBy;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @PrePersist
    protected void createTimestamps() {
        LocalDateTime now = LocalDateTime.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    protected void updateTimestamp() {
        updatedAt = LocalDateTime.now();
    }
}
