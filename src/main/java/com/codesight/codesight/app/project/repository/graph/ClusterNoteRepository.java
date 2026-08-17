package com.codesight.codesight.app.project.repository.graph;

import com.codesight.codesight.app.project.model.graph.ClusterNote;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface ClusterNoteRepository extends JpaRepository<ClusterNote, Long> {
    List<ClusterNote> findBySnapshotIdOrderByCreatedAtAsc(UUID snapshotId);
    void deleteBySnapshotId(UUID snapshotId);
}
