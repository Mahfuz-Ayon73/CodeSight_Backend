package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.ClusterDto;
import com.codesight.codesight.app.project.dto.graph.EdgeDto;
import com.codesight.codesight.app.project.dto.graph.GraphBlueprintDto;
import com.codesight.codesight.app.project.dto.graph.NodeDto;
import com.codesight.codesight.app.project.model.graph.CodebaseGraph;
import com.codesight.codesight.app.project.model.graph.GraphEdge;
import com.codesight.codesight.app.project.model.graph.GraphNode;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.graph.CodebaseGraphRepository;
import com.codesight.codesight.app.project.repository.graph.GraphEdgeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphNodeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class SnapshotPersistenceService {

    private final GraphSnapshotRepository snapshotRepository;
    private final GraphNodeRepository nodeRepository;
    private final GraphEdgeRepository edgeRepository;
    private final CodebaseGraphRepository codebaseGraphRepository;
    private final ObjectMapper objectMapper;

    private static final int BATCH_SIZE = 500;

    /**
     * Reads graph_blueprint.json from disk and persists a fully materialized snapshot
     * with GraphNode and GraphEdge rows. Also updates the CodebaseGraph pointer.
     *
     * Inserts are chunked into batches of {@value BATCH_SIZE} rows, each in its own
     * transaction, so a dropped connection (e.g. machine sleep) only loses the current
     * batch rather than the entire operation.
     *
     * @param projectId     owning project
     * @param blueprintPath path to graph_blueprint.json on disk
     * @param commitSha     git commit SHA (null for non-git uploads)
     * @param commitMessage git commit message (null for non-git uploads)
     * @param commitAuthor  git commit author (null for non-git uploads)
     * @param committedAt   git commit timestamp (null for non-git uploads)
     * @return the persisted snapshot ID
     */
    public UUID persistSnapshot(
            UUID projectId,
            Path blueprintPath,
            String commitSha,
            String commitMessage,
            String commitAuthor,
            LocalDateTime committedAt
    ) {
        log.info("[SNAPSHOT] Persisting snapshot for project {} from {}", projectId, blueprintPath);

        GraphBlueprintDto blueprint;
        try {
            blueprint = objectMapper.readValue(blueprintPath.toFile(), GraphBlueprintDto.class);
        } catch (IOException e) {
            log.error("[SNAPSHOT] Failed to read blueprint for project {}", projectId, e);
            throw new RuntimeException("Failed to read blueprint: " + e.getMessage(), e);
        }

        // Snapshot header — its own short transaction via repository's @Transactional
        GraphSnapshot snapshot = GraphSnapshot.builder()
                .projectId(projectId)
                .commitSha(commitSha)
                .commitMessage(commitMessage != null ? truncate(commitMessage, 1024) : null)
                .commitAuthor(commitAuthor != null ? truncate(commitAuthor, 256) : null)
                .committedAt(committedAt)
                .analyzedAt(LocalDateTime.now())
                .isMaterialized(true)
                .inProgress(false)
                .build();
        snapshot = snapshotRepository.save(snapshot);
        final UUID snapshotId = snapshot.getId();

        // Node batch-inserts — BATCH_SIZE rows per transaction to avoid long-held connections
        Map<String, Long> pathToNodeId = new HashMap<>();
        List<NodeDto> nodes = blueprint.getNodes();
        int totalNodes = 0;
        if (nodes != null) {
            List<GraphNode> nodeEntities = new ArrayList<>(nodes.size());
            for (NodeDto n : nodes) {
                boolean isEntry = "ENTRY_POINT".equals(n.getExecutionRole());
                boolean isSink  = "TERMINAL_SINK".equals(n.getExecutionRole());
                nodeEntities.add(GraphNode.builder()
                        .snapshotId(snapshotId)
                        .filePath(truncate(n.getCanonicalPath(), 1024))
                        .clusterId(truncate(n.getClusterId(), 128))
                        .isEntryPoint(isEntry)
                        .isSink(isSink)
                        .build());
            }
            List<GraphNode> allSaved = new ArrayList<>(nodeEntities.size());
            for (int i = 0; i < nodeEntities.size(); i += BATCH_SIZE) {
                List<GraphNode> batch = nodeEntities.subList(i, Math.min(i + BATCH_SIZE, nodeEntities.size()));
                allSaved.addAll(nodeRepository.saveAll(batch)); // own transaction per batch
            }
            for (int i = 0; i < allSaved.size(); i++) {
                pathToNodeId.put(nodes.get(i).getCanonicalPath(), allSaved.get(i).getId());
            }
            totalNodes = allSaved.size();
        }

        // Edge batch-inserts
        List<EdgeDto> edges = blueprint.getEdges();
        int totalEdges = 0;
        if (edges != null) {
            List<GraphEdge> edgeEntities = new ArrayList<>();
            for (EdgeDto e : edges) {
                Long srcId = pathToNodeId.get(e.getSource());
                Long tgtId = pathToNodeId.get(e.getTarget());
                if (srcId == null || tgtId == null) continue;
                edgeEntities.add(GraphEdge.builder()
                        .snapshotId(snapshotId)
                        .sourceNodeId(srcId)
                        .targetNodeId(tgtId)
                        .weight(e.getWeight())
                        .build());
            }
            for (int i = 0; i < edgeEntities.size(); i += BATCH_SIZE) {
                List<GraphEdge> batch = edgeEntities.subList(i, Math.min(i + BATCH_SIZE, edgeEntities.size()));
                edgeRepository.saveAll(batch); // own transaction per batch
            }
            totalEdges = edgeEntities.size();
        }

        // Update counts and CodebaseGraph — two short transactions
        int clustersCount = blueprint.getClusters() != null ? blueprint.getClusters().size() : 0;
        snapshot.setNodesCount(totalNodes);
        snapshot.setEdgesCount(totalEdges);
        snapshot.setClustersCount(clustersCount);
        snapshotRepository.save(snapshot);

        String paradigm = blueprint.getProjectMetadata() != null
                ? blueprint.getProjectMetadata().getDetectedParadigm()
                : null;
        String clustersSummary = buildClustersSummary(blueprint);

        CodebaseGraph codebaseGraph = codebaseGraphRepository.findByProjectId(projectId)
                .orElseGet(() -> CodebaseGraph.builder().projectId(projectId).build());
        codebaseGraph.setLatestSnapshotId(snapshotId);
        codebaseGraph.setParadigm(paradigm);
        codebaseGraph.setTotalNodes(totalNodes);
        codebaseGraph.setTotalEdges(totalEdges);
        codebaseGraph.setTotalClusters(clustersCount);
        codebaseGraph.setClustersSummary(clustersSummary);
        codebaseGraphRepository.save(codebaseGraph);

        log.info("[SNAPSHOT] Persisted snapshot {} for project {} ({} nodes, {} edges, {} clusters)",
                snapshotId, projectId, totalNodes, totalEdges, clustersCount);
        return snapshotId;
    }

    /** Overload for non-git uploads where commit metadata is unavailable. */
    public UUID persistSnapshot(UUID projectId, Path blueprintPath) {
        return persistSnapshot(projectId, blueprintPath, null, null, null, null);
    }

    private String buildClustersSummary(GraphBlueprintDto blueprint) {
        if (blueprint.getClusters() == null) return "[]";
        try {
            Map<String, Integer> nodeCount = new HashMap<>();
            if (blueprint.getNodes() != null) {
                for (NodeDto n : blueprint.getNodes()) {
                    nodeCount.merge(n.getClusterId(), 1, Integer::sum);
                }
            }
            List<Map<String, Object>> summary = new ArrayList<>();
            for (ClusterDto c : blueprint.getClusters()) {
                Map<String, Object> entry = new HashMap<>();
                entry.put("cluster_id", c.getId());
                entry.put("title", c.getSuggestedTitle() != null ? c.getSuggestedTitle() : c.getName());
                entry.put("summary", c.getFunctionalSummary());
                entry.put("node_count", nodeCount.getOrDefault(c.getId(), 0));
                summary.add(entry);
            }
            return objectMapper.writeValueAsString(summary);
        } catch (Exception e) {
            log.warn("[SNAPSHOT] Failed to build cluster summary", e);
            return "[]";
        }
    }

    private String truncate(String value, int maxLen) {
        if (value == null || value.length() <= maxLen) return value;
        return value.substring(0, maxLen);
    }
}
