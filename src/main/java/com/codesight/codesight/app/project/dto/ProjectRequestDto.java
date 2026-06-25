package com.codesight.codesight.app.project.dto;

import com.codesight.codesight.app.project.model.ProjectSourceType;
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
public class ProjectRequestDto {

    @NotBlank
    @Size(max = 120)
    private String name;

    @Size(max = 500)
    private String description;

    /** Optional. Defaults to LOCAL_ZIP when omitted. */
    private ProjectSourceType sourceType;

    /** Required when sourceType == GITHUB. */
    private String githubUrl;
}
