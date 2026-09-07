package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Read-side shape for GET .../graph/notes — one row per note attached to a
 * cluster within a snapshot. Several of these can share the same clusterId,
 * unlike {@link ClusterOverrideDto} which is one-per-cluster.
 */
@Data
@Builder
public class ClusterNoteDto {
    private Long id;
    private String clusterId;
    private String content;
    private String authorId;
    private String authorName;
    private LocalDateTime createdAt;
}
