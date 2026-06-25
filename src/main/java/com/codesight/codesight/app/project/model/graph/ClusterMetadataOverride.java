package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * A team member's manual override of a cluster's title and/or functional summary.
 * Same optimistic-locking pattern as NodeClusterOverride.
 */
@Entity
@Table(
    name = "cluster_metadata_override",
    uniqueConstraints = @UniqueConstraint(
        name = "uq_cluster_metadata_override_snapshot_cluster",
        columnNames = {"snapshot_id", "cluster_id"}
    ),
    indexes = {
        @Index(name = "idx_cluster_metadata_project_snapshot", columnList = "project_id, snapshot_id")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ClusterMetadataOverride {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Version
    private Long version;

    @Column(name = "project_id", nullable = false)
    private UUID projectId;

    @Column(name = "snapshot_id", nullable = false)
    private UUID snapshotId;

    @Column(name = "cluster_id", nullable = false, length = 128)
    private String clusterId;

    @Column(name = "original_title", length = 256)
    private String originalTitle;

    @Column(name = "override_title", length = 256)
    private String overrideTitle;

    @Column(name = "original_summary", length = 2048)
    private String originalSummary;

    @Column(name = "override_summary", length = 2048)
    private String overrideSummary;

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
