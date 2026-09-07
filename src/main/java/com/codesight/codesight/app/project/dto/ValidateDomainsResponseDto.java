package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class ValidateDomainsResponseDto {
    private Boolean success;

    @JsonProperty("llm_configured")
    private Boolean llmConfigured;

    @JsonProperty("clusters_checked")
    private Integer clustersChecked;

    @JsonProperty("clusters_confirmed")
    private Integer clustersConfirmed;

    @JsonProperty("clusters_with_suggestions")
    private Integer clustersWithSuggestions;

    @JsonProperty("error_message")
    private String errorMessage;
}
