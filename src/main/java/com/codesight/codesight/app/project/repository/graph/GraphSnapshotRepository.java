package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface GraphSnapshotRepository extends JpaRepository<GraphSnapshot, UUID> {

    List<GraphSnapshot> findByProjectIdOrderByAnalyzedAtDesc(UUID projectId);

    /** Latest snapshot per project — used by "My Workspace" bootstrap. */
    Optional<GraphSnapshot> findFirstByProjectIdOrderByAnalyzedAtDesc(UUID projectId);

    /** Whether a re-analysis is already in flight for this project. */
    boolean existsByProjectIdAndInProgressTrue(UUID projectId);

    @Modifying
    @Query("UPDATE GraphSnapshot s SET s.inProgress = false WHERE s.id = :id")
    int clearInProgress(@Param("id") UUID id);

    /**
     * Snapshots beyond the materialized-count that are still flagged as materialized
     * — used by the retention sweep to find candidates for demotion to blob-only.
     */
    @Query("""
        SELECT s FROM GraphSnapshot s
        WHERE s.projectId = :projectId
          AND s.isMaterialized = true
        ORDER BY s.analyzedAt DESC
    """)
    List<GraphSnapshot> findMaterializedByProjectOrderByNewest(@Param("projectId") UUID projectId, Pageable pageable);

    /** Total count per project — used by retention sweep to decide what to delete. */
    long countByProjectId(UUID projectId);

    /** Oldest snapshots per project — used by retention sweep to delete beyond the limit. */
    @Query("""
        SELECT s FROM GraphSnapshot s
        WHERE s.projectId = :projectId
        ORDER BY s.analyzedAt ASC
    """)
    List<GraphSnapshot> findByProjectOrderByOldest(@Param("projectId") UUID projectId, Pageable pageable);

    @Modifying
    @Query("DELETE FROM GraphSnapshot s WHERE s.analyzedAt < :cutoff AND s.isMaterialized = false")
    int deleteBlobSnapshotsOlderThan(@Param("cutoff") LocalDateTime cutoff);
}