package com.codesight.codesight.app.organization.repository;

import com.codesight.codesight.app.organization.model.OrganizationModel;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.UUID;

@Repository
public interface OrganizationRepository extends JpaRepository<OrganizationModel, UUID> {
    boolean existsBySlug(String slug);
}
