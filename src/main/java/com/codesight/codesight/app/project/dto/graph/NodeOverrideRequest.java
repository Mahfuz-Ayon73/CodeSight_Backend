package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

/**
 * Body for PUT /api/projects/{id}/graph/overrides/node — moves a file into a
 * different cluster than the analyzer assigned. {@code expectedVersion} is the
 * row's current @Version value; the controller compares it before saving and
 * returns 409 if another teammate has already edited this row.
 */
@Data
public class NodeOverrideRequest {

    @NotNull
    private UUID snapshotId;

    @NotBlank
    private String filePath;

    @NotBlank
    private String overrideClusterId;

    /** The @Version of the existing override row, or null when creating the first override. */
    private Long expectedVersion;
}