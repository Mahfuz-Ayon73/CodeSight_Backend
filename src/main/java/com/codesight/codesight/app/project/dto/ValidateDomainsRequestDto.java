package com.codesight.codesight.app.project.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class ValidateDomainsRequestDto {
    @JsonProperty("output_dir")
    private String outputDir;
}
