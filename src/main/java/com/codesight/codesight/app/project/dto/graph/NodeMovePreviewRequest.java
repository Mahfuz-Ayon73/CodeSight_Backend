package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

/** A non-mutating request to score moving a file to another leaf cluster. */
@Data
public class NodeMovePreviewRequest {

    @NotNull
    private UUID snapshotId;

    @NotBlank
    private String filePath;

    @NotBlank
    private String targetClusterId;
}
