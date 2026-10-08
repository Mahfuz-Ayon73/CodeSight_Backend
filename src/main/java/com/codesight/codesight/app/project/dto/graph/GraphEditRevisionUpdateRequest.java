package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class GraphEditRevisionUpdateRequest {
    @NotBlank
    @Size(max = 160)
    private String name;

    @Size(max = 1000)
    private String description;

    @NotNull
    @Valid
    @Size(max = 1000)
    private List<ManualGraphEdgeDto> addedEdges = new ArrayList<>();

    @NotNull
    @Size(max = 5000)
    private List<@NotBlank @Size(max = 2200) String> removedEdgeIds = new ArrayList<>();

    private Long expectedVersion;
}
