package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * Response shape for GET /api/projects/{id}/graph — the "My Workspace" endpoint.
 * Contains everything the ReactFlow canvas needs to render on first paint without
 * a follow-up fetch: pointer to the snapshot, cluster summaries (so the cluster
 * side panel can render), and a flag telling the client whether the graph is
 * materialized or only available as a compressed blob.
 */
@Data
@Builder
public class GraphWorkspaceResponse {

    private UUID projectId;
    private UUID snapshotId;
    private String paradigm;
    private String commitSha;
    private String commitMessage;
    private String commitAuthor;
    private LocalDateTime committedAt;
    private LocalDateTime analyzedAt;
    private String generatorVersion;

    private Integer totalNodes;
    private Integer totalEdges;
    private Integer totalClusters;

    /** Compact per-cluster summary used to bootstrap the cluster side panel. */
    private List<ClusterSummary> clusters;

    /** Whether the snapshot's nodes/edges are materialized as rows (true) or only available as a blob (false). */
    private Boolean isMaterialized;

    @Data
    @Builder
    public static class ClusterSummary {
        private String clusterId;
        private String title;
        private String summary;
        private Integer nodeCount;
    }
}