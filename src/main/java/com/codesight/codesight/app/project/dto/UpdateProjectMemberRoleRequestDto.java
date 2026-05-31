package com.codesight.codesight.app.project.dto;

import com.codesight.codesight.app.project.model.ProjectMemberRole;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class UpdateProjectMemberRoleRequestDto {

    @NotNull(message = "Role is required")
    private ProjectMemberRole role;
}
