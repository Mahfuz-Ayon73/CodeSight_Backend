package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.NodeClusterOverride;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface NodeClusterOverrideRepository extends JpaRepository<NodeClusterOverride, Long> {
    List<NodeClusterOverride> findBySnapshotId(UUID snapshotId);
    Optional<NodeClusterOverride> findBySnapshotIdAndFilePath(UUID snapshotId, String filePath);
    void deleteBySnapshotId(UUID snapshotId);
}
