package com.codesight.codesight.app.organization.repository;

import com.codesight.codesight.app.organization.model.OrganizationMemberModel;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface OrganizationMemberRepository extends JpaRepository<OrganizationMemberModel, UUID> {
    boolean existsByOrganizationIdAndUserId(UUID organizationId, UUID userId);

    Optional<OrganizationMemberModel> findByOrganizationIdAndUserId(UUID organizationId, UUID userId);

    List<OrganizationMemberModel> findAllByUserId(UUID userId);
}
