package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.NodeMoveEvaluationDto;
import com.codesight.codesight.app.project.dto.graph.NodeMovePreviewRequest;
import com.codesight.codesight.app.project.dto.graph.NodeOverrideRequest;
import com.codesight.codesight.app.project.model.graph.GraphEdge;
import com.codesight.codesight.app.project.model.graph.GraphNode;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.model.graph.NodeClusterOverride;
import com.codesight.codesight.app.project.repository.graph.GraphEdgeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphNodeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.app.project.repository.graph.NodeClusterOverrideRepository;
import com.codesight.codesight.common.exception.ConflictException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class NodeClusterOverrideServiceTest {

    @Mock
    private NodeClusterOverrideRepository overrideRepository;
    @Mock
    private GraphSnapshotRepository snapshotRepository;
    @Mock
    private GraphNodeRepository nodeRepository;
    @Mock
    private GraphEdgeRepository edgeRepository;

    @InjectMocks
    private NodeClusterOverrideService service;

    private final UUID projectId = UUID.randomUUID();
    private final UUID snapshotId = UUID.randomUUID();
    private final UUID userId = UUID.randomUUID();
    private List<GraphNode> nodes;

    @BeforeEach
    void setUp() {
        when(snapshotRepository.findById(snapshotId)).thenReturn(Optional.of(
                GraphSnapshot.builder().id(snapshotId).projectId(projectId).isMaterialized(true).build()));
        nodes = List.of(
                node(1L, "src/a.ts", "c1"),
                node(2L, "src/b.ts", "c1"),
                node(3L, "src/c.ts", "c2"),
                node(4L, "src/d.ts", "c2")
        );
    }

    @Test
    void previewReportsImprovementWithoutPersistingAnything() {
        when(nodeRepository.findBySnapshotId(snapshotId)).thenReturn(nodes);
        when(overrideRepository.findBySnapshotId(snapshotId)).thenReturn(List.of());
        when(edgeRepository.findBySnapshotId(snapshotId)).thenReturn(List.of(
                edge(1L, 3L, 1.0),
                edge(1L, 4L, 1.0),
                edge(3L, 4L, 1.0),
                edge(1L, 2L, 0.0)
        ));

        NodeMovePreviewRequest request = new NodeMovePreviewRequest();
        request.setSnapshotId(snapshotId);
        request.setFilePath("src/a.ts");
        request.setTargetClusterId("c2");

        NodeMoveEvaluationDto result = service.previewMove(projectId, request);

        assertEquals("IMPROVES", result.getVerdict());
        assertEquals("c1", result.getFromClusterId());
        assertEquals("c2", result.getToClusterId());
        assertTrue(result.getQualityScore().getDelta() > 0);
        assertTrue(result.getModularity().getDelta() > 0);
        assertTrue(result.getCohesion().getDelta() > 0);
        assertTrue(result.getFilePlacement().getDelta() > 0);
        assertEquals(2, result.getClusterSizes().getSourceBefore());
        assertEquals(1, result.getClusterSizes().getSourceAfter());
        verify(overrideRepository, never()).save(any());
        verify(nodeRepository, never()).save(any());
    }

    @Test
    void creatingOverridePreservesAnalyzerAssignedCluster() {
        GraphNode moved = nodes.get(0);
        when(nodeRepository.findBySnapshotIdAndFilePath(snapshotId, "src/a.ts"))
                .thenReturn(Optional.of(moved));
        when(nodeRepository.existsBySnapshotIdAndClusterId(snapshotId, "c2")).thenReturn(true);
        when(overrideRepository.findBySnapshotIdAndFilePath(snapshotId, "src/a.ts"))
                .thenReturn(Optional.empty());
        when(overrideRepository.save(any(NodeClusterOverride.class))).thenAnswer(invocation -> {
            NodeClusterOverride saved = invocation.getArgument(0);
            saved.setId(10L);
            saved.setVersion(0L);
            saved.setEditedAt(LocalDateTime.now());
            return saved;
        });

        NodeOverrideRequest request = request(null);
        service.upsertOverride(projectId, request, userId);

        ArgumentCaptor<NodeClusterOverride> captor = ArgumentCaptor.forClass(NodeClusterOverride.class);
        verify(overrideRepository).save(captor.capture());
        assertEquals("c1", captor.getValue().getOriginalClusterId());
        assertEquals("c2", captor.getValue().getOverrideClusterId());
    }

    @Test
    void staleOverrideVersionIsRejected() {
        when(nodeRepository.findBySnapshotIdAndFilePath(snapshotId, "src/a.ts"))
                .thenReturn(Optional.of(nodes.get(0)));
        when(nodeRepository.existsBySnapshotIdAndClusterId(snapshotId, "c2")).thenReturn(true);
        when(overrideRepository.findBySnapshotIdAndFilePath(snapshotId, "src/a.ts"))
                .thenReturn(Optional.of(NodeClusterOverride.builder()
                        .id(10L)
                        .version(2L)
                        .projectId(projectId)
                        .snapshotId(snapshotId)
                        .filePath("src/a.ts")
                        .originalClusterId("c1")
                        .overrideClusterId("c2")
                        .editedBy(userId)
                        .build()));

        assertThrows(ConflictException.class,
                () -> service.upsertOverride(projectId, request(1L), userId));
        verify(overrideRepository, never()).save(any());
    }

    private NodeOverrideRequest request(Long expectedVersion) {
        NodeOverrideRequest request = new NodeOverrideRequest();
        request.setSnapshotId(snapshotId);
        request.setFilePath("src/a.ts");
        request.setOverrideClusterId("c2");
        request.setExpectedVersion(expectedVersion);
        return request;
    }

    private GraphNode node(Long id, String path, String clusterId) {
        return GraphNode.builder()
                .id(id)
                .snapshotId(snapshotId)
                .filePath(path)
                .clusterId(clusterId)
                .build();
    }

    private GraphEdge edge(Long source, Long target, Double weight) {
        return GraphEdge.builder()
                .snapshotId(snapshotId)
                .sourceNodeId(source)
                .targetNodeId(target)
                .weight(weight)
                .build();
    }
}
