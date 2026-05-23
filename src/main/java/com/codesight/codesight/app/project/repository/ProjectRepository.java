package com.codesight.codesight.app.project.repository;

import com.codesight.codesight.app.project.model.ProjectModel;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface ProjectRepository extends JpaRepository<ProjectModel, UUID> {
    List<ProjectModel> findAllByOwnerId(UUID ownerId);
}
