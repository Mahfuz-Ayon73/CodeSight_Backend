package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class BlueprintDto {

    @JsonProperty("schema_version")
    private String schemaVersion;

    @JsonProperty("project_id")
    private String projectId;

    @JsonProperty("project_metadata")
    private ProjectMetadata projectMetadata;

    private List<NodeDto> nodes;
    private List<EdgeDto> edges;
    private List<ClusterDto> clusters;

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ProjectMetadata {
        @JsonProperty("detected_paradigm")
        private String detectedParadigm;

        @JsonProperty("total_nodes_indexed")
        private int totalNodesIndexed;

        @JsonProperty("total_edges")
        private int totalEdges;

        @JsonProperty("total_clusters")
        private int totalClusters;

        @JsonProperty("max_cluster_size")
        private Integer maxClusterSize;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class NodeDto {
        // v2 schema: id is a canonical path string
        private String id;

        @JsonProperty("cluster_id")
        private String clusterId;

        @JsonProperty("canonical_path")
        private String canonicalPath;

        @JsonProperty("centrality_score")
        private Double centralityScore;

        @JsonProperty("is_god_file")
        private Boolean isGodFile;

        @JsonProperty("execution_role")
        private String executionRole;

        @JsonProperty("external_dependencies")
        private List<String> externalDependencies;

        @JsonProperty("text_summary")
        private String textSummary;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class EdgeDto {
        // v2 schema: source/target are canonical path strings
        private String source;
        private String target;

        private Double weight;
        private String binding;

        @JsonProperty("called_names")
        private List<String> calledNames;

        @JsonProperty("is_dead_import")
        private Boolean isDeadImport;

        private String type;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ClusterDto {
        // v2 schema: id replaces cluster_id
        private String id;

        private String name;

        @JsonProperty("parent_cluster_id")
        private String parentClusterId;

        @JsonProperty("suggested_title")
        private String suggestedTitle;

        @JsonProperty("functional_summary")
        private String functionalSummary;
    }
}
