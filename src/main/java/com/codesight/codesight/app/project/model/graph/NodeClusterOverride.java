package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * A team member's manual override: "this file belongs in cluster X, not what
 * the analyzer said." Persists across reads but is discarded when a new
 * analysis produces a new snapshot (Option A from the design discussion).
 *
 * @Version provides optimistic locking — if two members edit the same file
 * concurrently, the second save throws OptimisticLockException, which the
 * controller maps to HTTP 409 Conflict.
 */
@Entity
@Table(
    name = "node_cluster_override",
    uniqueConstraints = @UniqueConstraint(
        name = "uq_node_cluster_override_snapshot_path",
        columnNames = {"snapshot_id", "file_path"}
    ),
    indexes = {
        @Index(name = "idx_node_override_project_snapshot", columnList = "project_id, snapshot_id")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class NodeClusterOverride {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Version
    private Long version;

    @Column(name = "project_id", nullable = false)
    private UUID projectId;

    @Column(name = "snapshot_id", nullable = false)
    private UUID snapshotId;

    @Column(name = "file_path", nullable = false, length = 1024)
    private String filePath;

    @Column(name = "original_cluster_id", nullable = false, length = 128)
    private String originalClusterId;

    @Column(name = "override_cluster_id", nullable = false, length = 128)
    private String overrideClusterId;

    @Column(name = "edited_by", nullable = false)
    private UUID editedBy;

    @Column(name = "edited_at", nullable = false)
    private LocalDateTime editedAt;

    @PrePersist
    @PreUpdate
    protected void touch() {
        editedAt = LocalDateTime.now();
    }
}
