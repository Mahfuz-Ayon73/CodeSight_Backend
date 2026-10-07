package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.InviteProjectMemberRequestDto;
import com.codesight.codesight.app.project.dto.ProjectMemberResponseDto;
import com.codesight.codesight.app.project.model.ProjectMemberModel;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ProjectMemberServiceTest {

    @Mock
    private ProjectMemberRepository projectMemberRepository;

    @Mock
    private ProjectRepository projectRepository;

    @Mock
    private UserRepository userRepository;

    @Mock
    private OrganizationAccessService organizationAccessService;

    @Mock
    private ProjectAccessService projectAccessService;

    @InjectMocks
    private ProjectMemberService projectMemberService;

    private final UUID organizationId = UUID.randomUUID();
    private final UUID projectId = UUID.randomUUID();
    private final UUID requesterId = UUID.randomUUID();

    @Test
    void listMembersReturnsUserDetailsAndProjectRoles() {
        UUID ownerId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        LocalDateTime joinedAt = LocalDateTime.of(2026, 1, 2, 3, 4);
        ProjectMemberModel owner = member(ownerId, ProjectMemberRole.OWNER, joinedAt);
        ProjectMemberModel member = member(memberId, ProjectMemberRole.MEMBER, joinedAt.plusDays(1));
        when(projectRepository.findByIdAndOrganizationId(projectId, organizationId))
                .thenReturn(Optional.of(project()));
        when(projectMemberRepository.findAllByProjectId(projectId)).thenReturn(List.of(owner, member));
        when(userRepository.findById(ownerId)).thenReturn(Optional.of(user(ownerId, "Ada", "Lovelace", "ada@example.com")));
        when(userRepository.findById(memberId)).thenReturn(Optional.of(user(memberId, "Grace", "Hopper", "grace@example.com")));

        List<ProjectMemberResponseDto> result = projectMemberService.listMembers(
                organizationId,
                projectId,
                requesterId
        );

        assertEquals(2, result.size());
        assertEquals("Ada", result.get(0).getUserFirstName());
        assertEquals("ada@example.com", result.get(0).getUserEmail());
        assertEquals(ProjectMemberRole.OWNER, result.get(0).getRole());
        assertEquals("Grace", result.get(1).getUserFirstName());
        assertEquals(joinedAt.plusDays(1), result.get(1).getJoinedAt());
        verify(organizationAccessService).requireMembership(organizationId, requesterId);
        verify(projectAccessService).requireMembership(projectId, requesterId);
    }

    @Test
    void listMembersKeepsMembershipWhenAUserProfileWasDeleted() {
        UUID removedUserId = UUID.randomUUID();
        when(projectRepository.findByIdAndOrganizationId(projectId, organizationId))
                .thenReturn(Optional.of(project()));
        when(projectMemberRepository.findAllByProjectId(projectId))
                .thenReturn(List.of(member(removedUserId, ProjectMemberRole.VIEWER, LocalDateTime.now())));
        when(userRepository.findById(removedUserId)).thenReturn(Optional.empty());

        ProjectMemberResponseDto result = projectMemberService
                .listMembers(organizationId, projectId, requesterId)
                .get(0);

        assertEquals(removedUserId, result.getUserId());
        assertNull(result.getUserEmail());
        assertNull(result.getUserFirstName());
    }

    @Test
    void listMembersRejectsAProjectFromAnotherOrganization() {
        when(projectRepository.findByIdAndOrganizationId(projectId, organizationId)).thenReturn(Optional.empty());

        assertThrows(
                ResourceNotFoundException.class,
                () -> projectMemberService.listMembers(organizationId, projectId, requesterId)
        );
        verify(projectMemberRepository, never()).findAllByProjectId(projectId);
    }

    @Test
    void inviteMemberSavesAnOrganizationMemberWithTheRequestedRole() {
        UUID inviteeId = UUID.randomUUID();
        UserModel invitee = user(inviteeId, "Linus", "Torvalds", "linus@example.com");
        InviteProjectMemberRequestDto request = invitation("linus@example.com", ProjectMemberRole.ADMIN);
        when(projectRepository.findByIdAndOrganizationId(projectId, organizationId))
                .thenReturn(Optional.of(project()));
        when(userRepository.findByEmail(request.getEmail())).thenReturn(Optional.of(invitee));
        when(projectMemberRepository.existsByProjectIdAndUserId(projectId, inviteeId)).thenReturn(false);
        when(projectMemberRepository.save(any(ProjectMemberModel.class))).thenAnswer(invocation -> {
            ProjectMemberModel saved = invocation.getArgument(0);
            saved.setId(UUID.randomUUID());
            return saved;
        });

        ProjectMemberResponseDto result = projectMemberService.inviteMember(
                organizationId,
                projectId,
                requesterId,
                request
        );

        assertEquals(inviteeId, result.getUserId());
        assertEquals("linus@example.com", result.getUserEmail());
        assertEquals(ProjectMemberRole.ADMIN, result.getRole());
        verify(projectAccessService).requireRole(projectId, requesterId, ProjectMemberRole.ADMIN);
        verify(organizationAccessService).requireMembership(organizationId, inviteeId);

        ArgumentCaptor<ProjectMemberModel> captor = ArgumentCaptor.forClass(ProjectMemberModel.class);
        verify(projectMemberRepository).save(captor.capture());
        assertEquals(organizationId, captor.getValue().getOrganizationId());
        assertEquals(projectId, captor.getValue().getProjectId());
    }

    @Test
    void inviteMemberRejectsAnExistingProjectMember() {
        UUID inviteeId = UUID.randomUUID();
        InviteProjectMemberRequestDto request = invitation("member@example.com", ProjectMemberRole.MEMBER);
        when(projectRepository.findByIdAndOrganizationId(projectId, organizationId))
                .thenReturn(Optional.of(project()));
        when(userRepository.findByEmail(request.getEmail()))
                .thenReturn(Optional.of(user(inviteeId, "Existing", "Member", request.getEmail())));
        when(projectMemberRepository.existsByProjectIdAndUserId(projectId, inviteeId)).thenReturn(true);

        assertThrows(
                ConflictException.class,
                () -> projectMemberService.inviteMember(organizationId, projectId, requesterId, request)
        );
        verify(projectMemberRepository, never()).save(any());
    }

    private ProjectModel project() {
        return ProjectModel.builder()
                .id(projectId)
                .name("CodeSight")
                .organizationId(organizationId)
                .ownerId(requesterId)
                .build();
    }

    private ProjectMemberModel member(UUID userId, ProjectMemberRole role, LocalDateTime joinedAt) {
        return ProjectMemberModel.builder()
                .id(UUID.randomUUID())
                .organizationId(organizationId)
                .projectId(projectId)
                .userId(userId)
                .role(role)
                .joinedAt(joinedAt)
                .build();
    }

    private UserModel user(UUID id, String firstName, String lastName, String email) {
        return UserModel.builder()
                .id(id)
                .firstName(firstName)
                .lastName(lastName)
                .email(email)
                .password("not-used")
                .handle(firstName.toLowerCase())
                .build();
    }

    private InviteProjectMemberRequestDto invitation(String email, ProjectMemberRole role) {
        InviteProjectMemberRequestDto request = new InviteProjectMemberRequestDto();
        request.setEmail(email);
        request.setRole(role);
        return request;
    }
}
