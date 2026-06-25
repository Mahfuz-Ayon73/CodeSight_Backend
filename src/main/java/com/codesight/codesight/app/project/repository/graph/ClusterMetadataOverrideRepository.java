package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.ClusterMetadataOverride;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface ClusterMetadataOverrideRepository extends JpaRepository<ClusterMetadataOverride, Long> {
    List<ClusterMetadataOverride> findBySnapshotId(UUID snapshotId);
    Optional<ClusterMetadataOverride> findBySnapshotIdAndClusterId(UUID snapshotId, String clusterId);
    void deleteBySnapshotId(UUID snapshotId);
}
