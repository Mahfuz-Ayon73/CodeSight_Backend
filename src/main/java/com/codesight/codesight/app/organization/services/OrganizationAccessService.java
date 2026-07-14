package com.codesight.codesight.app.organization.services;

import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import com.codesight.codesight.app.organization.repository.OrganizationMemberRepository;
import com.codesight.codesight.common.exception.UnauthorizedException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@RequiredArgsConstructor
public class OrganizationAccessService {

    private final OrganizationMemberRepository organizationMemberRepository;

    /** Throws if the user is not a member of the organization; returns their role otherwise. */
    public OrganizationMemberRole requireMembership(UUID organizationId, UUID userId) {
        return organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId)
                .orElseThrow(() -> new UnauthorizedException("You are not a member of this organization"))
                .getRole();
    }

    /** Throws if the user does not hold at least the given role. */
    public void requireRole(UUID organizationId, UUID userId, OrganizationMemberRole minimumRole) {
        OrganizationMemberRole actual = organizationMemberRepository
                .findByOrganizationIdAndUserId(organizationId, userId)
                .orElseThrow(() -> new UnauthorizedException("You are not a member of this organization"))
                .getRole();

        if (!hasAtLeast(actual, minimumRole)) {
            throw new UnauthorizedException(
                    "This action requires at least the " + minimumRole + " role");
        }
    }

    /** True if the user is the OWNER of this organization. Used for OR-checks (e.g. project deletion). */
    public boolean isOrganizationOwner(UUID organizationId, UUID userId) {
        return organizationMemberRepository
                .findByOrganizationIdAndUserId(organizationId, userId)
                .map(member -> member.getRole() == OrganizationMemberRole.OWNER)
                .orElse(false);
    }

    /**
     * Role hierarchy (highest → lowest): OWNER > ADMIN > MEMBER
     */
    private boolean hasAtLeast(OrganizationMemberRole actual, OrganizationMemberRole required) {
        return actual.ordinal() <= required.ordinal();
    }
}
