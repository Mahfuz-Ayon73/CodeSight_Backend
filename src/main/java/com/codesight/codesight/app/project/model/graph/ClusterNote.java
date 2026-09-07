package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * A free-form, MEMBER-tier annotation on a cluster (SRS 2.2.9) — distinct from
 * {@link ClusterMetadataOverride}, which is the ADMIN/OWNER-only name/summary
 * rename. Unlike the override, notes are additive: multiple rows can exist for
 * the same (snapshot, cluster) pair, each stamped with its own author and
 * timestamp, forming a running history rather than a single overwritable field.
 */
@Entity
@Table(
    name = "cluster_note",
    indexes = {
        @Index(name = "idx_cluster_note_snapshot_cluster", columnList = "snapshot_id, cluster_id"),
        @Index(name = "idx_cluster_note_project", columnList = "project_id")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ClusterNote {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "project_id", nullable = false)
    private UUID projectId;

    @Column(name = "snapshot_id", nullable = false)
    private UUID snapshotId;

    @Column(name = "cluster_id", nullable = false, length = 128)
    private String clusterId;

    @Column(name = "content", nullable = false, length = 2000)
    private String content;

    @Column(name = "author_id", nullable = false)
    private UUID authorId;

    /** Denormalized at write time so listing notes doesn't require joining User. */
    @Column(name = "author_name", nullable = false, length = 256)
    private String authorName;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
