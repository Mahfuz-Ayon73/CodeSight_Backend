package com.codesight.codesight.app.project.dto;

import com.codesight.codesight.app.project.model.ProjectMemberRole;
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
public class ProjectMemberResponseDto {
    private UUID id;
    private UUID projectId;
    private UUID userId;
    private String userEmail;
    private String userFirstName;
    private String userLastName;
    private ProjectMemberRole role;
    private LocalDateTime joinedAt;
}
