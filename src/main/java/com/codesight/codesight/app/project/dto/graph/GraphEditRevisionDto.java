package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

@Data
@Builder
public class GraphEditRevisionDto {
    private UUID id;
    private UUID snapshotId;
    private Integer revisionNumber;
    private String name;
    private String description;
    private List<ManualGraphEdgeDto> addedEdges;
    private List<String> removedEdgeIds;
    private UUID editedBy;
    private String editorName;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long version;
}
