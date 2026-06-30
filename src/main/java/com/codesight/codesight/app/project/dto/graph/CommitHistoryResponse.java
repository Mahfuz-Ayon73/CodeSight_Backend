package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.util.List;
import java.util.UUID;

@Data
@Builder
public class CommitHistoryResponse {
    private UUID projectId;
    private List<CommitDiffDto> commits;
    private List<SnapshotSummaryDto> snapshots;
}
