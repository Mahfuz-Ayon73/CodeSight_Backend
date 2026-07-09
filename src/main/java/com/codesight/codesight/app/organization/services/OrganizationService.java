package com.codesight.codesight.app.organization.services;

import com.codesight.codesight.app.organization.dto.OrganizationMemberResponseDto;
import com.codesight.codesight.app.organization.dto.OrganizationRequestDto;
import com.codesight.codesight.app.organization.dto.OrganizationResponseDto;
import com.codesight.codesight.app.organization.model.OrganizationMemberModel;
import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import com.codesight.codesight.app.organization.model.OrganizationModel;
import com.codesight.codesight.app.organization.repository.OrganizationMemberRepository;
import com.codesight.codesight.app.organization.repository.OrganizationRepository;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class OrganizationService {

    private final OrganizationRepository organizationRepository;
    private final OrganizationMemberRepository organizationMemberRepository;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectRepository projectRepository;
    private final UserRepository userRepository;

    @Transactional
    public OrganizationResponseDto createOrganization(OrganizationRequestDto request, UUID userId) {
        String slug = generateUniqueSlug(request.getName());

        OrganizationModel organization = OrganizationModel.builder()
                .name(request.getName().trim())
                .description(request.getDescription())
                .slug(slug)
                .createdByUserId(userId)
                .build();

        OrganizationModel saved = organizationRepository.save(organization);

        organizationMemberRepository.save(OrganizationMemberModel.builder()
                .organizationId(saved.getId())
                .userId(userId)
                .role(OrganizationMemberRole.OWNER)
                .build());

        return ObjectToDTOMapper.toOrganizationResponseDto(saved);
    }

    public OrganizationResponseDto getOrganization(UUID organizationId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        OrganizationModel organization = organizationRepository.findById(organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Organization not found"));
        return ObjectToDTOMapper.toOrganizationResponseDto(organization);
    }

    public List<OrganizationResponseDto> listMyOrganizations(UUID userId) {
        return organizationMemberRepository.findAllByUserId(userId).stream()
                .map(member -> organizationRepository.findById(member.getOrganizationId()))
                .filter(java.util.Optional::isPresent)
                .map(java.util.Optional::get)
                .map(ObjectToDTOMapper::toOrganizationResponseDto)
                .collect(Collectors.toList());
    }

    /** List all members of an organization. Requester must be a member. */
    public List<OrganizationMemberResponseDto> listMembers(UUID organizationId, UUID requesterId) {
        organizationAccessService.requireMembership(organizationId, requesterId);

        return organizationMemberRepository.findAllByOrganizationId(organizationId).stream()
                .map(member -> {
                    UserModel user = userRepository.findById(member.getUserId()).orElse(null);
                    return OrganizationMemberResponseDto.builder()
                            .id(member.getId())
                            .organizationId(member.getOrganizationId())
                            .userId(member.getUserId())
                            .userEmail(user != null ? user.getEmail() : null)
                            .userFirstName(user != null ? user.getFirstName() : null)
                            .userLastName(user != null ? user.getLastName() : null)
                            .role(member.getRole())
                            .joinedAt(member.getJoinedAt())
                            .build();
                })
                .collect(Collectors.toList());
    }

    /** Delete an organization. Requester must be OWNER, and the organization must have no projects. */
    @Transactional
    public void deleteOrganization(UUID organizationId, UUID requesterId) {
        organizationAccessService.requireRole(organizationId, requesterId, OrganizationMemberRole.OWNER);

        OrganizationModel organization = organizationRepository.findById(organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Organization not found"));

        if (!projectRepository.findAllByOrganizationId(organizationId).isEmpty()) {
            throw new ConflictException("Cannot delete an organization that still has projects");
        }

        organizationMemberRepository.deleteAllByOrganizationId(organizationId);
        organizationRepository.delete(organization);
    }

    private String generateUniqueSlug(String name) {
        String base = name.trim().toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("^-|-$", "");
        if (base.isBlank()) {
            base = "organization";
        }

        String slug = base;
        int suffix = 1;
        while (organizationRepository.existsBySlug(slug)) {
            slug = base + "-" + suffix++;
        }
        return slug;
    }
}
