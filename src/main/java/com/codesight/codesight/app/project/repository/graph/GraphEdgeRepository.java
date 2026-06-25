package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.GraphEdge;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface GraphEdgeRepository extends JpaRepository<GraphEdge, Long> {

    List<GraphEdge> findBySnapshotId(UUID snapshotId);

    @Modifying
    @Query("DELETE FROM GraphEdge e WHERE e.snapshotId = :snapshotId")
    int deleteBySnapshotId(@Param("snapshotId") UUID snapshotId);

    long countBySnapshotId(UUID snapshotId);
}