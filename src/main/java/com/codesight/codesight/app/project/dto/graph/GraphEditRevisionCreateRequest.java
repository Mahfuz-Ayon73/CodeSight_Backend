package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.UUID;

@Data
public class GraphEditRevisionCreateRequest {
    @NotNull
    private UUID snapshotId;

    @Size(max = 160)
    private String name;

    @Size(max = 1000)
    private String description;

    private UUID copyFromRevisionId;
}
