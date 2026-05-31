package com.codesight.codesight.app.organization.dto;

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
    private String slug;
    private UUID createdByUserId;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
