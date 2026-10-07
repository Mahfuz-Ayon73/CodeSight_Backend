package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.util.List;
import java.util.UUID;

/** Before/after graph-partition quality for a proposed file move. */
@Data
@Builder
public class NodeMoveEvaluationDto {
    private UUID snapshotId;
    private String filePath;
    private String fromClusterId;
    private String toClusterId;
    private String verdict;
    private MetricDelta qualityScore;
    private MetricDelta modularity;
    private MetricDelta cohesion;
    private MetricDelta coupling;
    private MetricDelta sizeBalance;
    private MetricDelta filePlacement;
    private ClusterSizeDelta clusterSizes;
    private List<String> reasons;
    private String methodology;

    @Data
    @Builder
    public static class MetricDelta {
        private double before;
        private double after;
        private double delta;
    }

    @Data
    @Builder
    public static class ClusterSizeDelta {
        private int sourceBefore;
        private int sourceAfter;
        private int targetBefore;
        private int targetAfter;
    }
}
