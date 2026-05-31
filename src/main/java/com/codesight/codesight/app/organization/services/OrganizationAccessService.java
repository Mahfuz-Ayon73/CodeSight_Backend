package com.codesight.codesight.app.organization.services;

import com.codesight.codesight.app.organization.repository.OrganizationMemberRepository;
import com.codesight.codesight.common.exception.UnauthorizedException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@RequiredArgsConstructor
public class OrganizationAccessService {

    private final OrganizationMemberRepository organizationMemberRepository;

    public void requireMembership(UUID organizationId, UUID userId) {
        if (!organizationMemberRepository.existsByOrganizationIdAndUserId(organizationId, userId)) {
            throw new UnauthorizedException("You are not a member of this organization");
        }
    }
}
