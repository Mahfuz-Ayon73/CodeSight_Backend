package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

/**
 * Body for PUT /api/projects/{id}/graph/overrides/cluster — renames or rewrites
 * the human-readable label/summary of a cluster. Same optimistic-locking
 * pattern as NodeOverrideRequest.
 */
@Data
public class ClusterOverrideRequest {

    @NotNull
    private UUID snapshotId;

    @NotBlank
    private String clusterId;

    private String overrideTitle;
    private String overrideSummary;

    private Long expectedVersion;
}