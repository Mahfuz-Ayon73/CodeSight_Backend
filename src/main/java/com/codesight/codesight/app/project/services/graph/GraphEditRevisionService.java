package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.GraphEditRevisionCreateRequest;
import com.codesight.codesight.app.project.dto.graph.GraphEditRevisionDto;
import com.codesight.codesight.app.project.dto.graph.GraphEditRevisionUpdateRequest;
import com.codesight.codesight.app.project.dto.graph.ManualGraphEdgeDto;
import com.codesight.codesight.app.project.model.graph.GraphEditRevision;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.graph.GraphEditRevisionRepository;
import com.codesight.codesight.app.project.repository.graph.GraphNodeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class GraphEditRevisionService {

    private final GraphEditRevisionRepository revisionRepository;
    private final GraphSnapshotRepository snapshotRepository;
    private final GraphNodeRepository nodeRepository;
    private final UserRepository userRepository;
    private final ObjectMapper objectMapper;

    public List<GraphEditRevisionDto> list(UUID projectId, UUID snapshotId) {
        requireSnapshot(projectId, snapshotId);
        return revisionRepository.findByProjectIdAndSnapshotIdOrderByRevisionNumberAsc(projectId, snapshotId)
                .stream().map(this::toDto).toList();
    }

    @Transactional
    public GraphEditRevisionDto create(UUID projectId, GraphEditRevisionCreateRequest request, UUID userId) {
        requireSnapshot(projectId, request.getSnapshotId());

        String added = "[]";
        String removed = "[]";
        if (request.getCopyFromRevisionId() != null) {
            GraphEditRevision base = requireRevision(projectId, request.getCopyFromRevisionId());
            if (!base.getSnapshotId().equals(request.getSnapshotId())) {
                throw new BadRequestException("A revision can only be copied within the same analyzer snapshot");
            }
            added = base.getAddedEdgesJson();
            removed = base.getRemovedEdgeIdsJson();
        }

        int nextNumber = revisionRepository
                .findFirstByProjectIdAndSnapshotIdOrderByRevisionNumberDesc(projectId, request.getSnapshotId())
                .map(r -> r.getRevisionNumber() + 1)
                .orElse(1);

        GraphEditRevision saved = revisionRepository.save(GraphEditRevision.builder()
                .projectId(projectId)
                .snapshotId(request.getSnapshotId())
                .revisionNumber(nextNumber)
                .name(trimToNull(request.getName()) == null
                        ? "Version " + nextNumber
                        : request.getName().trim())
                .description(trimToNull(request.getDescription()))
                .addedEdgesJson(added)
                .removedEdgeIdsJson(removed)
                .editedBy(userId)
                .build());
        return toDto(saved);
    }

    @Transactional
    public void delete(UUID projectId, UUID revisionId) {
        revisionRepository.delete(requireRevision(projectId, revisionId));
    }

    @Transactional
    public GraphEditRevisionDto update(
            UUID projectId,
            UUID revisionId,
            GraphEditRevisionUpdateRequest request,
            UUID userId
    ) {
        GraphEditRevision revision = requireRevision(projectId, revisionId);
        if (request.getExpectedVersion() != null
                && !request.getExpectedVersion().equals(revision.getVersion())) {
            throw new ConflictException("This map version was edited by someone else — refresh and try again");
        }

        validateEdges(revision.getSnapshotId(), request.getAddedEdges());
        revision.setName(request.getName().trim());
        revision.setDescription(trimToNull(request.getDescription()));
        revision.setAddedEdgesJson(writeJson(request.getAddedEdges()));
        revision.setRemovedEdgeIdsJson(writeJson(request.getRemovedEdgeIds().stream().distinct().toList()));
        revision.setEditedBy(userId);
        return toDto(revisionRepository.save(revision));
    }

    private void validateEdges(UUID snapshotId, List<ManualGraphEdgeDto> edges) {
        Set<String> filePaths = nodeRepository.findBySnapshotId(snapshotId).stream()
                .map(n -> n.getFilePath())
                .collect(java.util.stream.Collectors.toSet());
        Set<String> edgeIds = new HashSet<>();
        for (ManualGraphEdgeDto edge : edges) {
            if (edge.getSource().equals(edge.getTarget())) {
                throw new BadRequestException("A file cannot be connected to itself");
            }
            if (!filePaths.contains(edge.getSource()) || !filePaths.contains(edge.getTarget())) {
                throw new BadRequestException("A manual relationship references a file outside this snapshot");
            }
            if (!edgeIds.add(edge.getId())) {
                throw new BadRequestException("Manual relationship IDs must be unique");
            }
            edge.setType("USER_DEFINED");
            edge.setLabel(trimToNull(edge.getLabel()));
            edge.setNote(trimToNull(edge.getNote()));
        }
    }

    private GraphSnapshot requireSnapshot(UUID projectId, UUID snapshotId) {
        GraphSnapshot snapshot = snapshotRepository.findById(snapshotId)
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));
        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }
        return snapshot;
    }

    private GraphEditRevision requireRevision(UUID projectId, UUID revisionId) {
        return revisionRepository.findByIdAndProjectId(revisionId, projectId)
                .orElseThrow(() -> new ResourceNotFoundException("Map version not found"));
    }

    private GraphEditRevisionDto toDto(GraphEditRevision revision) {
        UserModel editor = userRepository.findById(revision.getEditedBy()).orElse(null);
        String editorName = editor == null
                ? "Unknown editor"
                : (editor.getFirstName() + " " + editor.getLastName()).trim();
        return GraphEditRevisionDto.builder()
                .id(revision.getId())
                .snapshotId(revision.getSnapshotId())
                .revisionNumber(revision.getRevisionNumber())
                .name(revision.getName())
                .description(revision.getDescription())
                .addedEdges(readEdges(revision.getAddedEdgesJson()))
                .removedEdgeIds(readStrings(revision.getRemovedEdgeIdsJson()))
                .editedBy(revision.getEditedBy())
                .editorName(editorName)
                .createdAt(revision.getCreatedAt())
                .updatedAt(revision.getUpdatedAt())
                .version(revision.getVersion())
                .build();
    }

    private List<ManualGraphEdgeDto> readEdges(String json) {
        try {
            return objectMapper.readValue(json, new TypeReference<>() {});
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Stored manual relationships are invalid", e);
        }
    }

    private List<String> readStrings(String json) {
        try {
            return objectMapper.readValue(json, new TypeReference<>() {});
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Stored removed relationships are invalid", e);
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new BadRequestException("Map changes could not be serialized");
        }
    }

    private String trimToNull(String value) {
        if (value == null) return null;
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
