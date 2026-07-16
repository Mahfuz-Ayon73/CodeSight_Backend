package com.codesight.codesight.app.project.dto.graph;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class NodeDto {
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