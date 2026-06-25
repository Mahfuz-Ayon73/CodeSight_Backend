package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.GraphNode;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface GraphNodeRepository extends JpaRepository<GraphNode, Long> {

    List<GraphNode> findBySnapshotId(UUID snapshotId);

    /** Cluster membership used by the ReactFlow canvas. */
    List<GraphNode> findBySnapshotIdAndClusterId(UUID snapshotId, String clusterId);

    /** Bulk delete when a snapshot is demoted to blob-only. */
    @Modifying
    @Query("DELETE FROM GraphNode n WHERE n.snapshotId = :snapshotId")
    int deleteBySnapshotId(@Param("snapshotId") UUID snapshotId);

    long countBySnapshotId(UUID snapshotId);
}