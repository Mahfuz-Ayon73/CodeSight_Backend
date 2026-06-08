package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.BlueprintDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class ProjectAnalysisBlueprintService {

    private final ProjectRepository projectRepository;
    private final OrganizationAccessService organizationAccessService;
    private final ObjectMapper objectMapper;

    @Value("${codesight.analysis.output-dir:./storage/analysis}")
    private String analysisOutputDir;

    public BlueprintDto getBlueprint(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);

        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (project.getAnalysisStatus() != AnalysisStatus.COMPLETED) {
            throw new ResourceNotFoundException(
                "Analysis not yet complete. Current status: " + project.getAnalysisStatus()
            );
        }

        Path blueprintPath = Paths.get(analysisOutputDir)
                .resolve(organizationId.toString())
                .resolve(projectId.toString())
                .resolve("graph_blueprint.json");

        log.info("[BLUEPRINT] Looking for blueprint at: {}", blueprintPath.toAbsolutePath());

        if (!Files.exists(blueprintPath)) {
            log.warn("[BLUEPRINT] File not found at: {}", blueprintPath.toAbsolutePath());
            throw new ResourceNotFoundException("Blueprint file not found for this project");
        }

        try {
            return objectMapper.readValue(blueprintPath.toFile(), BlueprintDto.class);
        } catch (IOException e) {
            log.error("Failed to read blueprint for project {}", projectId, e);
            throw new RuntimeException("Failed to read analysis results: " + e.getMessage());
        }
    }
}
