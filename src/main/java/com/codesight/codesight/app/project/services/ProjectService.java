package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.ProjectRequestDto;
import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.exception.UnauthorizedException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ProjectService {

    private final ProjectRepository projectRepository;
    private final OrganizationAccessService organizationAccessService;

    @Transactional
    public ProjectResponseDto createProject(UUID organizationId, ProjectRequestDto request, UUID ownerId) {
        organizationAccessService.requireMembership(organizationId, ownerId);

        ProjectModel project = ProjectModel.builder()
                .name(request.getName().trim())
                .description(request.getDescription())
                .organizationId(organizationId)
                .ownerId(ownerId)
                .analysisStatus(AnalysisStatus.PENDING_UPLOAD)
                .build();

        return ObjectToDTOMapper.toProjectResponseDto(projectRepository.save(project));
    }

    public ProjectResponseDto getProject(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
        return ObjectToDTOMapper.toProjectResponseDto(project);
    }

    public List<ProjectResponseDto> listProjects(UUID organizationId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        return projectRepository.findAllByOrganizationId(organizationId).stream()
                .map(ObjectToDTOMapper::toProjectResponseDto)
                .collect(Collectors.toList());
    }

    @Transactional
    public void deleteProject(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (!project.getOwnerId().equals(userId)) {
            throw new UnauthorizedException("Only the project owner can delete this project");
        }

        projectRepository.delete(project);
    }
}
