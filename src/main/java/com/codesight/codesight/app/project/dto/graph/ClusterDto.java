package com.codesight.codesight.app.project.dto.graph;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class ClusterDto {
    private String id;
    private String name;

    @JsonProperty("parent_cluster_id")
    private String parentClusterId;

    @JsonProperty("suggested_title")
    private String suggestedTitle;

    @JsonProperty("functional_summary")
    private String functionalSummary;
}