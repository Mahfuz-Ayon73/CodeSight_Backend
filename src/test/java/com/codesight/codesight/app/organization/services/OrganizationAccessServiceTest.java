package com.codesight.codesight.app.organization.services;

import com.codesight.codesight.app.organization.model.OrganizationMemberModel;
import com.codesight.codesight.app.organization.model.OrganizationMemberRole;
import com.codesight.codesight.app.organization.repository.OrganizationMemberRepository;
import com.codesight.codesight.common.exception.UnauthorizedException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrganizationAccessServiceTest {

    @Mock
    private OrganizationMemberRepository organizationMemberRepository;

    @InjectMocks
    private OrganizationAccessService organizationAccessService;

    private final UUID organizationId = UUID.randomUUID();
    private final UUID userId = UUID.randomUUID();

    @Test
    void requireMembershipReturnsTheUsersRole() {
        when(organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId))
                .thenReturn(Optional.of(member(OrganizationMemberRole.ADMIN)));

        assertEquals(
                OrganizationMemberRole.ADMIN,
                organizationAccessService.requireMembership(organizationId, userId)
        );
    }

    @Test
    void requireMembershipRejectsNonMembers() {
        when(organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId))
                .thenReturn(Optional.empty());

        assertThrows(
                UnauthorizedException.class,
                () -> organizationAccessService.requireMembership(organizationId, userId)
        );
    }

    @Test
    void requireRoleAllowsHigherRoles() {
        when(organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId))
                .thenReturn(Optional.of(member(OrganizationMemberRole.OWNER)));

        organizationAccessService.requireRole(organizationId, userId, OrganizationMemberRole.ADMIN);
    }

    @Test
    void requireRoleRejectsLowerRoles() {
        when(organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId))
                .thenReturn(Optional.of(member(OrganizationMemberRole.MEMBER)));

        assertThrows(
                UnauthorizedException.class,
                () -> organizationAccessService.requireRole(
                        organizationId,
                        userId,
                        OrganizationMemberRole.ADMIN
                )
        );
    }

    @Test
    void isOrganizationOwnerOnlyReturnsTrueForOwner() {
        when(organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId))
                .thenReturn(Optional.of(member(OrganizationMemberRole.OWNER)));

        assertTrue(organizationAccessService.isOrganizationOwner(organizationId, userId));
    }

    @Test
    void isOrganizationOwnerReturnsFalseForMissingMembership() {
        when(organizationMemberRepository.findByOrganizationIdAndUserId(organizationId, userId))
                .thenReturn(Optional.empty());

        assertFalse(organizationAccessService.isOrganizationOwner(organizationId, userId));
    }

    private OrganizationMemberModel member(OrganizationMemberRole role) {
        return OrganizationMemberModel.builder()
                .organizationId(organizationId)
                .userId(userId)
                .role(role)
                .build();
    }
}
