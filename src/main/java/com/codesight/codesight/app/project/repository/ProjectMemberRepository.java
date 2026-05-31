package com.codesight.codesight.app.project.repository;

import com.codesight.codesight.app.project.model.ProjectMemberModel;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface ProjectMemberRepository extends JpaRepository<ProjectMemberModel, UUID> {

    boolean existsByProjectIdAndUserId(UUID projectId, UUID userId);

    Optional<ProjectMemberModel> findByProjectIdAndUserId(UUID projectId, UUID userId);

    List<ProjectMemberModel> findAllByProjectId(UUID projectId);

    @Transactional
    void deleteByProjectIdAndUserId(UUID projectId, UUID userId);
}
