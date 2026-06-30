package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.UUID;

@Data
@Builder
public class SnapshotSummaryDto {
    private UUID snapshotId;
    private String commitSha;
    private String shortSha;
    private String commitMessage;
    private String commitAuthor;
    private LocalDateTime committedAt;
    private LocalDateTime analyzedAt;
    private boolean isAnalyzed;
    private String deltaJson;
    private Integer nodesCount;
    private Integer edgesCount;
    private Integer clustersCount;
}
