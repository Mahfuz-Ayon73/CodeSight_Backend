package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class AnalysisStatusResponseDto {
    @JsonProperty("task_id")
    private String taskId;

    @JsonProperty("project_id")
    private String projectId;

    private String status;

    private String stage;

    private String message;

    @JsonProperty("blueprint_path")
    private String blueprintPath;

    @JsonProperty("error_message")
    private String errorMessage;

    @JsonProperty("execution_time_seconds")
    private Double executionTimeSeconds;
}
