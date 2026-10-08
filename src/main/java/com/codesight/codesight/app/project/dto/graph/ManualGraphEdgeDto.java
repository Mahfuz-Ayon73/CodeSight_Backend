package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ManualGraphEdgeDto {
    @NotBlank
    @Size(max = 128)
    private String id;

    @NotBlank
    @Size(max = 1024)
    private String source;

    @NotBlank
    @Size(max = 1024)
    private String target;

    @Size(max = 64)
    @Builder.Default
    private String type = "USER_DEFINED";

    @Size(max = 256)
    private String label;

    @Size(max = 1000)
    private String note;
}
