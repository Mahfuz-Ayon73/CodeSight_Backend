package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.ProjectRequestDto;
import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectMemberModel;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.model.ProjectSourceType;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.UnauthorizedException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ProjectServiceTest {

    @Mock
    private ProjectRepository projectRepository;

    @Mock
    private ProjectMemberRepository projectMemberRepository;

    @Mock
    private OrganizationAccessService organizationAccessService;

    @Mock
    private AnalysisProgressStore analysisProgressStore;

    @InjectMocks
    private ProjectService projectService;

    private final UUID organizationId = UUID.randomUUID();
    private final UUID userId = UUID.randomUUID();

    @Test
    void ownersCanListEveryProjectInTheirOrganization() {
        List<ProjectModel> projects = List.of(project("One", UUID.randomUUID()), project("Two", UUID.randomUUID()));
        when(organizationAccessService.requireMembership(organizationId, userId))
                .thenReturn(OrganizationMemberRole.OWNER);
        when(projectRepository.findAllByOrganizationId(organizationId)).thenReturn(projects);

        List<ProjectResponseDto> result = projectService.listProjects(organizationId, userId);

        assertEquals(List.of("One", "Two"), result.stream().map(ProjectResponseDto::getName).toList());
    }

    @Test
    void membersOnlySeeProjectsTheyOwnOrWereAddedTo() {
        ProjectModel owned = project("Owned", userId);
        ProjectModel assigned = project("Assigned", UUID.randomUUID());
        ProjectModel hidden = project("Hidden", UUID.randomUUID());
        when(organizationAccessService.requireMembership(organizationId, userId))
                .thenReturn(OrganizationMemberRole.MEMBER);
        when(projectRepository.findAllByOrganizationId(organizationId))
                .thenReturn(List.of(owned, assigned, hidden));
        when(projectMemberRepository.existsByProjectIdAndUserId(assigned.getId(), userId)).thenReturn(true);
        when(projectMemberRepository.existsByProjectIdAndUserId(hidden.getId(), userId)).thenReturn(false);

        List<ProjectResponseDto> result = projectService.listProjects(organizationId, userId);

        assertEquals(List.of("Owned", "Assigned"), result.stream().map(ProjectResponseDto::getName).toList());
    }

    @Test
    void membersCannotFetchAnUnassignedProject() {
        ProjectModel hidden = project("Hidden", UUID.randomUUID());
        when(organizationAccessService.requireMembership(organizationId, userId))
                .thenReturn(OrganizationMemberRole.MEMBER);
        when(projectRepository.findByIdAndOrganizationId(hidden.getId(), organizationId))
                .thenReturn(Optional.of(hidden));
        when(projectMemberRepository.existsByProjectIdAndUserId(hidden.getId(), userId)).thenReturn(false);

        assertThrows(
                UnauthorizedException.class,
                () -> projectService.getProject(organizationId, hidden.getId(), userId)
        );
    }

    @Test
    void creatingAProjectAutomaticallyAddsItsOwnerAsAProjectMember() {
        UUID projectId = UUID.randomUUID();
        ProjectRequestDto request = ProjectRequestDto.builder()
                .name("  Collaboration API  ")
                .description("Project member endpoints")
                .build();
        when(projectRepository.save(any(ProjectModel.class))).thenAnswer(invocation -> {
            ProjectModel saved = invocation.getArgument(0);
            saved.setId(projectId);
            return saved;
        });

        ProjectResponseDto result = projectService.createProject(organizationId, request, userId);

        assertEquals(projectId, result.getId());
        assertEquals("Collaboration API", result.getName());
        assertEquals(ProjectSourceType.LOCAL_ZIP, result.getSourceType());
        assertEquals(AnalysisStatus.PENDING_UPLOAD, result.getAnalysisStatus());

        ArgumentCaptor<ProjectMemberModel> memberCaptor = ArgumentCaptor.forClass(ProjectMemberModel.class);
        verify(projectMemberRepository).save(memberCaptor.capture());
        assertEquals(projectId, memberCaptor.getValue().getProjectId());
        assertEquals(organizationId, memberCaptor.getValue().getOrganizationId());
        assertEquals(userId, memberCaptor.getValue().getUserId());
        assertEquals(ProjectMemberRole.OWNER, memberCaptor.getValue().getRole());
        verify(organizationAccessService).requireRole(organizationId, userId, OrganizationMemberRole.OWNER);
    }

    @Test
    void githubProjectsRequireARepositoryUrl() {
        ProjectRequestDto request = ProjectRequestDto.builder()
                .name("Missing repository")
                .sourceType(ProjectSourceType.GITHUB)
                .githubUrl(" ")
                .build();

        assertThrows(
                BadRequestException.class,
                () -> projectService.createProject(organizationId, request, userId)
        );
        verify(projectRepository, never()).save(any());
        verify(projectMemberRepository, never()).save(any());
    }

    private ProjectModel project(String name, UUID ownerId) {
        return ProjectModel.builder()
                .id(UUID.randomUUID())
                .name(name)
                .organizationId(organizationId)
                .ownerId(ownerId)
                .sourceType(ProjectSourceType.LOCAL_ZIP)
                .analysisStatus(AnalysisStatus.PENDING_UPLOAD)
                .build();
    }
}
