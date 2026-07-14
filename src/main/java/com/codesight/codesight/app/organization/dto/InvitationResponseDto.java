package com.codesight.codesight.app.organization.dto;

import com.codesight.codesight.app.organization.model.InvitationStatus;
import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class InvitationResponseDto {
    private UUID id;
    private UUID organizationId;
    private String organizationName;
    private UUID projectId;
    private String projectName;
    private String email;
    private OrganizationMemberRole role;
    private InvitationStatus status;
    private String invitedByName;
    private LocalDateTime expiresAt;
    private boolean expired;
}
