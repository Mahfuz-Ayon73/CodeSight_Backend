package com.codesight.codesight.app.project.dto.graph;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * Mirrors the JSON shape emitted by python_analyzer/analyzer.py (schema_version 2.0).
 * Used as the wire format between the analyzer and the Spring backend, and as the
 * reference document for cluster_summary persistence.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class GraphBlueprintDto {

    @JsonProperty("schema_version")
    private String schemaVersion;

    @JsonProperty("project_id")
    private String projectId;

    @JsonProperty("project_metadata")
    private ProjectMetadata projectMetadata;

    private List<ClusterDto> clusters;
    private List<NodeDto> nodes;
    private List<EdgeDto> edges;

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ProjectMetadata {
        @JsonProperty("detected_paradigm")
        private String detectedParadigm;

        @JsonProperty("total_nodes_indexed")
        private Integer totalNodesIndexed;

        @JsonProperty("total_edges")
        private Integer totalEdges;

        @JsonProperty("total_clusters")
        private Integer totalClusters;

        @JsonProperty("max_cluster_size")
        private Integer maxClusterSize;
    }
}