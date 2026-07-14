package com.codesight.codesight.app.organization.services;

import com.codesight.codesight.app.auth.services.VerificationEmailService;
import com.codesight.codesight.app.organization.dto.CreateInvitationRequestDto;
import com.codesight.codesight.app.organization.dto.InvitationResponseDto;
import com.codesight.codesight.app.organization.model.InvitationStatus;
import com.codesight.codesight.app.organization.model.OrganizationInvitationModel;
import com.codesight.codesight.app.organization.model.OrganizationMemberModel;
import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import com.codesight.codesight.app.organization.model.OrganizationModel;
import com.codesight.codesight.app.organization.repository.OrganizationInvitationRepository;
import com.codesight.codesight.app.organization.repository.OrganizationMemberRepository;
import com.codesight.codesight.app.organization.repository.OrganizationRepository;
import com.codesight.codesight.app.project.model.ProjectMemberModel;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.exception.UnauthorizedException;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class OrganizationInvitationService {

    private final OrganizationInvitationRepository invitationRepository;
    private final OrganizationRepository organizationRepository;
    private final OrganizationMemberRepository organizationMemberRepository;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectRepository projectRepository;
    private final ProjectMemberRepository projectMemberRepository;
    private final UserRepository userRepository;
    private final VerificationEmailService verificationEmailService;

    @Value("${app.frontend.url}")
    private String frontendUrl;

    @Transactional
    public InvitationResponseDto createInvitation(UUID organizationId, UUID requesterId, CreateInvitationRequestDto request) {
        organizationAccessService.requireRole(organizationId, requesterId, OrganizationMemberRole.ADMIN);

        OrganizationModel organization = organizationRepository.findById(organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Organization not found"));

        ProjectModel project = null;
        if (request.getProjectId() != null) {
            project = projectRepository.findByIdAndOrganizationId(request.getProjectId(), organizationId)
                    .orElseThrow(() -> new BadRequestException("Project does not belong to this organization"));
        }

        userRepository.findByEmail(request.getEmail()).ifPresent(existingUser -> {
            if (organizationMemberRepository.existsByOrganizationIdAndUserId(organizationId, existingUser.getId())) {
                throw new ConflictException("This person is already a member of the organization");
            }
        });

        UserModel requester = userRepository.findById(requesterId)
                .orElseThrow(() -> new ResourceNotFoundException("User not found"));

        // Reuse an existing PENDING invitation row (refreshing it) instead of creating a duplicate;
        // only block the request if that existing invitation hasn't expired yet.
        OrganizationInvitationModel existingInvitation = invitationRepository
                .findByOrganizationIdAndEmailIgnoreCaseAndStatus(organizationId, request.getEmail(), InvitationStatus.PENDING)
                .orElse(null);
        if (existingInvitation != null && existingInvitation.getExpiresAt().isAfter(LocalDateTime.now())) {
            throw new ConflictException("An invitation is already pending for this email");
        }
        OrganizationInvitationModel invitation = existingInvitation != null
                ? existingInvitation
                : OrganizationInvitationModel.builder().build();

        String token = UUID.randomUUID().toString();
        invitation.setOrganizationId(organizationId);
        invitation.setProjectId(request.getProjectId());
        invitation.setEmail(request.getEmail());
        invitation.setRole(request.getRole());
        invitation.setProjectRole(project != null ? toProjectRole(request.getRole()) : null);
        invitation.setToken(token);
        invitation.setStatus(InvitationStatus.PENDING);
        invitation.setInvitedByUserId(requesterId);
        invitation.setExpiresAt(LocalDateTime.now().plusDays(7));

        invitationRepository.save(invitation);

        String requesterName = (requester.getFirstName() + " " + requester.getLastName()).trim();
        String acceptUrl = frontendUrl + "/invitations/" + token;
        verificationEmailService.sendInvitationEmail(request.getEmail(), requesterName, organization.getName(), acceptUrl);

        return toDto(invitation, organization.getName(), project != null ? project.getName() : null, requesterName);
    }

    public InvitationResponseDto getInvitation(String token) {
        OrganizationInvitationModel invitation = invitationRepository.findByToken(token)
                .orElseThrow(() -> new ResourceNotFoundException("Invitation not found"));

        OrganizationModel organization = organizationRepository.findById(invitation.getOrganizationId())
                .orElseThrow(() -> new ResourceNotFoundException("Organization not found"));
        String projectName = invitation.getProjectId() != null
                ? projectRepository.findById(invitation.getProjectId()).map(ProjectModel::getName).orElse(null)
                : null;
        String inviterName = userRepository.findById(invitation.getInvitedByUserId())
                .map(u -> (u.getFirstName() + " " + u.getLastName()).trim())
                .orElse("Someone");

        return toDto(invitation, organization.getName(), projectName, inviterName);
    }

    @Transactional
    public InvitationResponseDto acceptInvitation(String token, UUID currentUserId, String currentUserEmail) {
        OrganizationInvitationModel invitation = invitationRepository.findByToken(token)
                .orElseThrow(() -> new ResourceNotFoundException("Invitation not found"));

        if (invitation.getStatus() != InvitationStatus.PENDING) {
            throw new ConflictException("This invitation is no longer valid");
        }
        if (invitation.getExpiresAt().isBefore(LocalDateTime.now())) {
            throw new ConflictException("This invitation has expired");
        }
        if (!invitation.getEmail().equalsIgnoreCase(currentUserEmail)) {
            throw new UnauthorizedException("This invitation was sent to a different email address");
        }

        if (!organizationMemberRepository.existsByOrganizationIdAndUserId(invitation.getOrganizationId(), currentUserId)) {
            organizationMemberRepository.save(OrganizationMemberModel.builder()
                    .organizationId(invitation.getOrganizationId())
                    .userId(currentUserId)
                    .role(invitation.getRole())
                    .build());
        }

        if (invitation.getProjectId() != null
                && !projectMemberRepository.existsByProjectIdAndUserId(invitation.getProjectId(), currentUserId)) {
            projectMemberRepository.save(ProjectMemberModel.builder()
                    .projectId(invitation.getProjectId())
                    .userId(currentUserId)
                    .organizationId(invitation.getOrganizationId())
                    .role(invitation.getProjectRole() != null ? invitation.getProjectRole() : ProjectMemberRole.MEMBER)
                    .build());
        }

        invitation.setStatus(InvitationStatus.ACCEPTED);
        invitation.setAcceptedAt(LocalDateTime.now());
        invitationRepository.save(invitation);

        OrganizationModel organization = organizationRepository.findById(invitation.getOrganizationId())
                .orElseThrow(() -> new ResourceNotFoundException("Organization not found"));
        return toDto(invitation, organization.getName(), null, null);
    }

    private ProjectMemberRole toProjectRole(OrganizationMemberRole role) {
        return switch (role) {
            case OWNER -> ProjectMemberRole.OWNER;
            case ADMIN -> ProjectMemberRole.ADMIN;
            case MEMBER -> ProjectMemberRole.MEMBER;
        };
    }

    private InvitationResponseDto toDto(
            OrganizationInvitationModel invitation, String organizationName, String projectName, String invitedByName
    ) {
        return InvitationResponseDto.builder()
                .id(invitation.getId())
                .organizationId(invitation.getOrganizationId())
                .organizationName(organizationName)
                .projectId(invitation.getProjectId())
                .projectName(projectName)
                .email(invitation.getEmail())
                .role(invitation.getRole())
                .status(invitation.getStatus())
                .invitedByName(invitedByName)
                .expiresAt(invitation.getExpiresAt())
                .expired(invitation.getExpiresAt().isBefore(LocalDateTime.now()))
                .build();
    }
}
