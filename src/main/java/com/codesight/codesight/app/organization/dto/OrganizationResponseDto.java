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
public class OrganizationResponseDto {
    private UUID id;
    private String name;
    private String description;
    private String slug;
    private UUID createdByUserId;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    /** The requesting user's own role in this organization (OWNER/ADMIN/MEMBER). */
    private OrganizationMemberRole myRole;
}
