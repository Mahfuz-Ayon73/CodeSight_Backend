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

    /** Journey roots — where a reader should start. Null for pre-journey analyses. */
    @JsonProperty("entry_points")
    private List<EntryPointDto> entryPoints;

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

        @JsonProperty("detected_domains")
        private List<String> detectedDomains;

        @JsonProperty("journey_coverage")
        private JourneyCoverage journeyCoverage;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class JourneyCoverage {
        private Integer reached;
        private Integer total;

        @JsonProperty("unreached_count")
        private Integer unreachedCount;

        @JsonProperty("unreached_sample")
        private List<String> unreachedSample;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class EntryPointDto {
        private String file;
        private String url;
        /** "page" | "api" | "server" */
        private String kind;

        @JsonProperty("auth_state")
        private String authState;

        private Double confidence;
        private List<String> evidence;

        /** Layouts wrapping this screen, outermost first, ending with the file itself. */
        @JsonProperty("render_chain")
        private List<String> renderChain;

        @JsonProperty("cluster_id")
        private String clusterId;

        private String domain;

        @JsonProperty("reach_count")
        private Integer reachCount;

        @JsonProperty("own_reach_count")
        private Integer ownReachCount;

        @JsonProperty("reach_ratio")
        private Double reachRatio;

        @JsonProperty("is_landing")
        private Boolean isLanding;
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

        private String domain;

        @JsonProperty("domain_confidence")
        private Double domainConfidence;

        @JsonProperty("domain_source")
        private String domainSource;
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

        /**
         * True for convention/similarity edges the analyzer inferred rather than
         * read from an import. The tour excludes them, so dropping this field
         * here would make it walk hops that do not exist in the source.
         */
        @JsonProperty("is_synthetic")
        private Boolean isSynthetic;

        private String type;

        @JsonProperty("source_line")
        private Integer sourceLine;

        @JsonProperty("target_line")
        private Integer targetLine;
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

        private String domain;

        @JsonProperty("domain_type")
        private String domainType;

        @JsonProperty("domain_confidence")
        private Double domainConfidence;

        @JsonProperty("domain_evidence")
        private List<String> domainEvidence;
    }
}
