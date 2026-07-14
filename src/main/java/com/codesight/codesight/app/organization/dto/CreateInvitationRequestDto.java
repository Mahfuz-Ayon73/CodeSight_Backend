package com.codesight.codesight.app.organization.dto;

import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

@Data
public class CreateInvitationRequestDto {

    @NotBlank(message = "Email is required")
    @Email(message = "Must be a valid email address")
    private String email;

    @NotNull(message = "Role is required")
    private OrganizationMemberRole role;

    /** Optional — also enrolls the invitee in this project (must belong to the same organization). */
    private UUID projectId;
}
