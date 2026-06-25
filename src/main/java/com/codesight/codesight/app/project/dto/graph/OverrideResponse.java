package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * Returned after a successful override write. Includes the new @Version so the
 * client can chain subsequent edits without re-reading the row.
 */
@Data
@Builder
public class OverrideResponse {
    private Long id;
    private Long version;
    private UUID snapshotId;
    private String editedBy;
    private LocalDateTime editedAt;
}