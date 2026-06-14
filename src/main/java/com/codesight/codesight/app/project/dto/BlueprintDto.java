package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
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

    @JsonProperty("execution_sequences")
    private List<Object> executionSequences;

    @Data
    public static class ProjectMetadata {
        @JsonProperty("detected_paradigm")
        private String detectedParadigm;

        @JsonProperty("total_nodes_indexed")
        private int totalNodesIndexed;

        @JsonProperty("total_edges")
        private int totalEdges;

        @JsonProperty("total_clusters")
        private int totalClusters;
    }

    @Data
    public static class NodeDto {
        private Integer id;

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
    public static class EdgeDto {
        @JsonProperty("source_id")
        private Integer sourceId;

        @JsonProperty("target_id")
        private Integer targetId;

        private Double weight;

        private String binding;

        @JsonProperty("called_names")
        private List<String> calledNames;

        @JsonProperty("is_dead_import")
        private Boolean isDeadImport;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ClusterDto {
        @JsonProperty("cluster_id")
        private String clusterId;

        @JsonProperty("suggested_title")
        private String suggestedTitle;

        @JsonProperty("functional_summary")
        private String functionalSummary;

        @JsonProperty("node_ids")
        private List<Integer> nodeIds;

        private List<String> nodes;

        @JsonProperty("referenced_by_clusters")
        private List<String> referencedByClusters;
    }
}
