package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.UUID;

/**
 * Body for POST /api/.../graph/notes — attaches a new note to a cluster.
 * Notes are additive (see {@link com.codesight.codesight.app.project.model.graph.ClusterNote}),
 * so unlike ClusterOverrideRequest there is no expectedVersion — nothing is
 * ever overwritten in place.
 */
@Data
public class ClusterNoteRequest {

    @NotNull
    private UUID snapshotId;

    @NotBlank
    private String clusterId;

    @NotBlank
    @Size(max = 2000)
    private String content;
}
