package com.codesight.codesight.app.organization.dto;

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
public class OrganizationMemberResponseDto {
    private UUID id;
    private UUID organizationId;
    private UUID userId;
    private String userEmail;
    private String userFirstName;
    private String userLastName;
    private OrganizationMemberRole role;
    private LocalDateTime joinedAt;
}
