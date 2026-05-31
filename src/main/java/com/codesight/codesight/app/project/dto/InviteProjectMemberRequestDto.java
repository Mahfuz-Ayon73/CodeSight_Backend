package com.codesight.codesight.app.project.dto;

import com.codesight.codesight.app.project.model.ProjectMemberRole;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class InviteProjectMemberRequestDto {

    @NotBlank(message = "Email is required")
    @Email(message = "Must be a valid email address")
    private String email;

    @NotNull(message = "Role is required")
    private ProjectMemberRole role;
}
