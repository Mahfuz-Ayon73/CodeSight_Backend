package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.GraphEditRevision;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface GraphEditRevisionRepository extends JpaRepository<GraphEditRevision, UUID> {
    List<GraphEditRevision> findByProjectIdAndSnapshotIdOrderByRevisionNumberAsc(UUID projectId, UUID snapshotId);
    Optional<GraphEditRevision> findByIdAndProjectId(UUID id, UUID projectId);
    Optional<GraphEditRevision> findFirstByProjectIdAndSnapshotIdOrderByRevisionNumberDesc(UUID projectId, UUID snapshotId);
}
