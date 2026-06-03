package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class AnalysisRequestDto {
    @JsonProperty("project_id")
    private String projectId;
    
    @JsonProperty("repo_path")
    private String repoPath;
    
    @JsonProperty("output_dir")
    private String outputDir;
    
    @JsonProperty("purge_source")
    private Boolean purgeSource = true;
}