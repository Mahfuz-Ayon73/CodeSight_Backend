package com.codesight.codesight.app.organization.repository;

import com.codesight.codesight.app.organization.model.InvitationStatus;
import com.codesight.codesight.app.organization.model.OrganizationInvitationModel;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface OrganizationInvitationRepository extends JpaRepository<OrganizationInvitationModel, UUID> {
    Optional<OrganizationInvitationModel> findByToken(String token);

    Optional<OrganizationInvitationModel> findByOrganizationIdAndEmailIgnoreCaseAndStatus(
            UUID organizationId, String email, InvitationStatus status
    );
}
