package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.ProjectRequestDto;
import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.dto.ProjectUpdateRequestDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectMemberModel;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.model.ProjectSourceType;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.exception.UnauthorizedException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class ProjectService {

    private final ProjectRepository projectRepository;
    private final ProjectMemberRepository projectMemberRepository;
    private final OrganizationAccessService organizationAccessService;
    private final AnalysisProgressStore analysisProgressStore;

    @Transactional
    public ProjectResponseDto createProject(UUID organizationId, ProjectRequestDto request, UUID ownerId) {
        organizationAccessService.requireMembership(organizationId, ownerId);

        ProjectSourceType sourceType = request.getSourceType() != null
                ? request.getSourceType()
                : ProjectSourceType.LOCAL_ZIP;

        if (sourceType == ProjectSourceType.GITHUB
                && (request.getGithubUrl() == null || request.getGithubUrl().isBlank())) {
            throw new BadRequestException("githubUrl is required when sourceType is GITHUB");
        }

        ProjectModel project = ProjectModel.builder()
                .name(request.getName().trim())
                .description(request.getDescription())
                .organizationId(organizationId)
                .ownerId(ownerId)
                .sourceType(sourceType)
                .githubUrl(sourceType == ProjectSourceType.GITHUB ? request.getGithubUrl() : null)
                .analysisStatus(AnalysisStatus.PENDING_UPLOAD)
                .build();

        ProjectModel saved = projectRepository.save(project);
        log.info("[PROJECT-CREATE] org={} project={} owner={} sourceType={} githubUrl={}",
                organizationId, saved.getId(), ownerId, sourceType, saved.getGithubUrl());

        // Auto-enroll the creator as OWNER in project_members
        projectMemberRepository.save(ProjectMemberModel.builder()
                .projectId(saved.getId())
                .userId(ownerId)
                .organizationId(organizationId)
                .role(ProjectMemberRole.OWNER)
                .build());

        return ObjectToDTOMapper.toProjectResponseDto(saved);
    }

    public ProjectResponseDto getProject(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
        ProjectResponseDto dto = ObjectToDTOMapper.toProjectResponseDto(project);

        if (dto.getAnalysisStatus() == AnalysisStatus.IN_PROGRESS) {
            AnalysisProgressStore.AnalysisProgress progress = analysisProgressStore.get(projectId.toString());
            dto.setAnalysisStage(progress.stage());
            dto.setAnalysisMessage(progress.message());
        }

        return dto;
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

        requireProjectOwnerOrOrgOwner(organizationId, userId, project);

        projectRepository.delete(project);
    }

    @Transactional
    public ProjectResponseDto updateProject(
            UUID organizationId, UUID projectId, ProjectUpdateRequestDto request, UUID userId
    ) {
        organizationAccessService.requireMembership(organizationId, userId);
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        requireProjectOwnerOrOrgOwner(organizationId, userId, project);

        project.setDescription(request.getDescription());
        ProjectModel saved = projectRepository.save(project);
        return ObjectToDTOMapper.toProjectResponseDto(saved);
    }

    /** Only the project's own owner or the parent organization's owner may modify/delete it. */
    private void requireProjectOwnerOrOrgOwner(UUID organizationId, UUID userId, ProjectModel project) {
        boolean isProjectOwner = project.getOwnerId().equals(userId);
        boolean isOrgOwner = organizationAccessService.isOrganizationOwner(organizationId, userId);

        if (!isProjectOwner && !isOrgOwner) {
            throw new UnauthorizedException("Only the project owner or the organization owner can do this");
        }
    }
}
