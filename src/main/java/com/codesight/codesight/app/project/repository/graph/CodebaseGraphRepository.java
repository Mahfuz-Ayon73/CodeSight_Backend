package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.CodebaseGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface CodebaseGraphRepository extends JpaRepository<CodebaseGraph, UUID> {
    Optional<CodebaseGraph> findByProjectId(UUID projectId);
}