package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.ClusterOverrideDto;
import com.codesight.codesight.app.project.dto.graph.ClusterOverrideRequest;
import com.codesight.codesight.app.project.dto.graph.OverrideResponse;
import com.codesight.codesight.app.project.model.graph.ClusterMetadataOverride;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.graph.ClusterMetadataOverrideRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Creates or updates a {@link ClusterMetadataOverride} row — a team member's manual
 * rename/re-summary of an LLM-suggested cluster label. Same optimistic-locking pattern
 * as the (still-unwired) node-override sibling: an absent {@code expectedVersion} means
 * "create if missing", a present one must match the row's current version or the write
 * is rejected as a conflict.
 */
@Service
@RequiredArgsConstructor
public class ClusterOverrideService {

    private final ClusterMetadataOverrideRepository overrideRepository;
    private final GraphSnapshotRepository snapshotRepository;

    @Transactional
    public OverrideResponse upsertOverride(UUID projectId, ClusterOverrideRequest request, UUID userId) {
        GraphSnapshot snapshot = snapshotRepository.findById(request.getSnapshotId())
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));

        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }

        Optional<ClusterMetadataOverride> existingOpt = overrideRepository
                .findBySnapshotIdAndClusterId(request.getSnapshotId(), request.getClusterId());

        ClusterMetadataOverride override;
        if (existingOpt.isPresent()) {
            override = existingOpt.get();
            if (request.getExpectedVersion() != null
                    && !request.getExpectedVersion().equals(override.getVersion())) {
                throw new ConflictException("This cluster was edited by someone else — refresh and try again");
            }
            override.setOverrideTitle(request.getOverrideTitle());
            override.setOverrideSummary(request.getOverrideSummary());
            override.setEditedBy(userId);
        } else {
            if (request.getExpectedVersion() != null) {
                throw new ConflictException("Cluster override no longer exists — refresh and try again");
            }
            override = ClusterMetadataOverride.builder()
                    .projectId(projectId)
                    .snapshotId(request.getSnapshotId())
                    .clusterId(request.getClusterId())
                    .overrideTitle(request.getOverrideTitle())
                    .overrideSummary(request.getOverrideSummary())
                    .editedBy(userId)
                    .build();
        }

        ClusterMetadataOverride saved = overrideRepository.save(override);

        return OverrideResponse.builder()
                .id(saved.getId())
                .version(saved.getVersion())
                .snapshotId(saved.getSnapshotId())
                .editedBy(saved.getEditedBy().toString())
                .editedAt(saved.getEditedAt())
                .build();
    }

    public List<ClusterOverrideDto> listOverrides(UUID projectId, UUID snapshotId) {
        GraphSnapshot snapshot = snapshotRepository.findById(snapshotId)
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));

        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }

        return overrideRepository.findBySnapshotId(snapshotId).stream()
                .map(o -> ClusterOverrideDto.builder()
                        .clusterId(o.getClusterId())
                        .overrideTitle(o.getOverrideTitle())
                        .overrideSummary(o.getOverrideSummary())
                        .version(o.getVersion())
                        .build())
                .toList();
    }
}
