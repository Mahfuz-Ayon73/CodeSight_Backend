package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.InviteProjectMemberRequestDto;
import com.codesight.codesight.app.project.dto.ProjectMemberResponseDto;
import com.codesight.codesight.app.project.dto.UpdateProjectMemberRoleRequestDto;
import com.codesight.codesight.app.project.model.ProjectMemberModel;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ProjectMemberService {

    private final ProjectMemberRepository projectMemberRepository;
    private final ProjectRepository projectRepository;
    private final UserRepository userRepository;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    /**
     * Invite a user (by email) to a project.
     * Requester must be at least ADMIN in the project.
     */
    @Transactional
    public ProjectMemberResponseDto inviteMember(
            UUID organizationId,
            UUID projectId,
            UUID requesterId,
            InviteProjectMemberRequestDto request
    ) {
        organizationAccessService.requireMembership(organizationId, requesterId);
        projectAccessService.requireRole(projectId, requesterId, ProjectMemberRole.ADMIN);

        // Verify the project exists within this organization
        getProjectOrThrow(projectId, organizationId);

        UserModel invitee = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new ResourceNotFoundException(
                        "No user found with email: " + request.getEmail()));

        if (projectMemberRepository.existsByProjectIdAndUserId(projectId, invitee.getId())) {
            throw new ConflictException("User is already a member of this project");
        }

        // Invitee must belong to the same organization
        organizationAccessService.requireMembership(organizationId, invitee.getId());

        ProjectMemberModel member = ProjectMemberModel.builder()
                .projectId(projectId)
                .userId(invitee.getId())
                .organizationId(organizationId)
                .role(request.getRole())
                .build();

        return toDto(projectMemberRepository.save(member), invitee);
    }

    /** List all members of a project. Requester must be a project member. */
    public List<ProjectMemberResponseDto> listMembers(
            UUID organizationId,
            UUID projectId,
            UUID requesterId
    ) {
        organizationAccessService.requireMembership(organizationId, requesterId);
        projectAccessService.requireMembership(projectId, requesterId);

        return projectMemberRepository.findAllByProjectId(projectId).stream()
                .map(member -> {
                    UserModel user = userRepository.findById(member.getUserId())
                            .orElse(null);
                    return toDto(member, user);
                })
                .collect(Collectors.toList());
    }

    /** Update a member's role. Requester must be OWNER. */
    @Transactional
    public ProjectMemberResponseDto updateMemberRole(
            UUID organizationId,
            UUID projectId,
            UUID targetUserId,
            UUID requesterId,
            UpdateProjectMemberRoleRequestDto request
    ) {
        organizationAccessService.requireMembership(organizationId, requesterId);
        projectAccessService.requireRole(projectId, requesterId, ProjectMemberRole.OWNER);

        ProjectMemberModel member = projectMemberRepository
                .findByProjectIdAndUserId(projectId, targetUserId)
                .orElseThrow(() -> new ResourceNotFoundException("Member not found in this project"));

        // Prevent changing the owner's own role
        if (member.getRole() == ProjectMemberRole.OWNER) {
            throw new ConflictException("Cannot change the role of the project owner");
        }

        member.setRole(request.getRole());
        UserModel user = userRepository.findById(member.getUserId()).orElse(null);
        return toDto(projectMemberRepository.save(member), user);
    }

    /** Remove a member from a project. Requester must be ADMIN or higher, cannot remove OWNER. */
    @Transactional
    public void removeMember(
            UUID organizationId,
            UUID projectId,
            UUID targetUserId,
            UUID requesterId
    ) {
        organizationAccessService.requireMembership(organizationId, requesterId);
        projectAccessService.requireRole(projectId, requesterId, ProjectMemberRole.ADMIN);

        ProjectMemberModel member = projectMemberRepository
                .findByProjectIdAndUserId(projectId, targetUserId)
                .orElseThrow(() -> new ResourceNotFoundException("Member not found in this project"));

        if (member.getRole() == ProjectMemberRole.OWNER) {
            throw new ConflictException("Cannot remove the project owner");
        }

        projectMemberRepository.deleteByProjectIdAndUserId(projectId, targetUserId);
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private ProjectModel getProjectOrThrow(UUID projectId, UUID organizationId) {
        return projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
    }

    private ProjectMemberResponseDto toDto(ProjectMemberModel member, UserModel user) {
        return ProjectMemberResponseDto.builder()
                .id(member.getId())
                .projectId(member.getProjectId())
                .userId(member.getUserId())
                .userEmail(user != null ? user.getEmail() : null)
                .userFirstName(user != null ? user.getFirstName() : null)
                .userLastName(user != null ? user.getLastName() : null)
                .role(member.getRole())
                .joinedAt(member.getJoinedAt())
                .build();
    }
}
