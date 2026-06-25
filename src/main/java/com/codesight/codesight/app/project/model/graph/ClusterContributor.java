package com.codesight.codesight.app.project.model.graph;

import jakarta.persistence.*;
import lombok.*;

import java.util.UUID;

/**
 * Skeleton for the future "most impactful coder per cluster" feature.
 * Schema is in place so the snapshot pipeline can populate rows as a side
 * effect; the read-side query that ranks authors will be added later.
 */
@Entity
@Table(
    name = "cluster_contributor",
    indexes = {
        @Index(name = "idx_cluster_contributor_snapshot_cluster", columnList = "snapshot_id, cluster_id"),
        @Index(name = "idx_cluster_contributor_author", columnList = "snapshot_id, author_email")
    }
)
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ClusterContributor {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "snapshot_id", nullable = false)
    private UUID snapshotId;

    @Column(name = "cluster_id", nullable = false, length = 128)
    private String clusterId;

    @Column(name = "author_email", nullable = false, length = 256)
    private String authorEmail;

    @Column(name = "author_name", length = 256)
    private String authorName;

    /** How many distinct files in this cluster this author has touched (in this snapshot's window). */
    @Column(name = "files_touched")
    @Builder.Default
    private Integer filesTouched = 0;

    /** Number of commits by this author touching this cluster. */
    @Column(name = "commits_count")
    @Builder.Default
    private Integer commitsCount = 0;

    /** Aggregate lines added+removed across all commits by this author in this cluster. */
    @Column(name = "lines_changed")
    @Builder.Default
    private Long linesChanged = 0L;
}
