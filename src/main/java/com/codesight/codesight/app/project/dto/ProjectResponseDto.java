package com.codesight.codesight.app.project.dto;

import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectSourceType;
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
public class ProjectResponseDto {
    private UUID id;
    private String name;
    private String description;
    private UUID organizationId;
    private UUID ownerId;
    private ProjectSourceType sourceType;
    private String githubUrl;
    private AnalysisStatus analysisStatus;
    private String analysisStage;
    private String analysisMessage;
    private String uploadErrorMessage;
    private LocalDateTime uploadedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
