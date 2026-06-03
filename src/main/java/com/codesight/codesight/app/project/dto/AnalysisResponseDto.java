package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class AnalysisResponseDto {
    private Boolean success;
    
    @JsonProperty("project_id")
    private String projectId;
    
    @JsonProperty("blueprint_path")
    private String blueprintPath;
    
    @JsonProperty("error_message")
    private String errorMessage;
    
    @JsonProperty("execution_time_seconds")
    private Double executionTimeSeconds;
}