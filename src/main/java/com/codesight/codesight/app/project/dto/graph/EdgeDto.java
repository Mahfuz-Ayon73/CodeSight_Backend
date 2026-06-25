package com.codesight.codesight.app.project.dto.graph;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class EdgeDto {
    private String source;
    private String target;
    private String type;
    private Double weight;
    private String binding;

    @JsonProperty("called_names")
    private List<String> calledNames;

    @JsonProperty("is_dead_import")
    private Boolean isDeadImport;
}