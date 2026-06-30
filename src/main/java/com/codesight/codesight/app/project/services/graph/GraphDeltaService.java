package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.GraphBlueprintDto;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class GraphDeltaService {

    private final GraphSnapshotRepository snapshotRepository;
    private final ObjectMapper objectMapper;

    /**
     * Computes the structural delta between two blueprint files and stores
     * the result in {@code GraphSnapshot.deltaJson} for the {@code newSnapshotId}.
     *
     * Delta shape:
     * {
     *   "added_clusters":   ["c_001", ...],
     *   "removed_clusters": ["c_002", ...],
     *   "added_nodes":      ["src/foo.ts", ...],
     *   "removed_nodes":    ["src/old.ts", ...],
     *   "modified_nodes":   ["src/bar.ts", ...],   // same path, different cluster or role
     *   "moved_nodes":      [{"file":"src/baz.ts","from_cluster":"c_1","to_cluster":"c_2"}, ...]
     * }
     */
    @Transactional
    public void computeAndStoreDelta(
            UUID newSnapshotId,
            Path prevBlueprintPath,
            Path newBlueprintPath
    ) {
        GraphBlueprintDto prev;
        GraphBlueprintDto next;
        try {
            prev = objectMapper.readValue(prevBlueprintPath.toFile(), GraphBlueprintDto.class);
            next = objectMapper.readValue(newBlueprintPath.toFile(), GraphBlueprintDto.class);
        } catch (IOException e) {
            log.error("[DELTA] Failed to read blueprints for snapshot {}", newSnapshotId, e);
            return;
        }

        String deltaJson = computeDelta(prev, next);

        Optional<GraphSnapshot> snapshotOpt = snapshotRepository.findById(newSnapshotId);
        if (snapshotOpt.isEmpty()) {
            log.warn("[DELTA] Snapshot {} not found — skipping delta storage", newSnapshotId);
            return;
        }
        GraphSnapshot snapshot = snapshotOpt.get();
        snapshot.setDeltaJson(deltaJson);
        snapshotRepository.save(snapshot);
        log.info("[DELTA] Stored delta for snapshot {}", newSnapshotId);
    }

    /** Computes delta JSON string without persisting — useful for on-the-fly queries. */
    public String computeDelta(GraphBlueprintDto prev, GraphBlueprintDto next) {
        // Cluster sets
        Set<String> prevClusters = clusterIds(prev);
        Set<String> nextClusters = clusterIds(next);

        List<String> addedClusters   = new ArrayList<>();
        List<String> removedClusters = new ArrayList<>();
        for (String id : nextClusters) if (!prevClusters.contains(id)) addedClusters.add(id);
        for (String id : prevClusters) if (!nextClusters.contains(id)) removedClusters.add(id);

        // Node maps: path → cluster assignment
        Map<String, String> prevNodes = nodeClusterMap(prev);
        Map<String, String> nextNodes = nodeClusterMap(next);

        List<String> addedNodes   = new ArrayList<>();
        List<String> removedNodes = new ArrayList<>();
        List<String> modifiedNodes = new ArrayList<>();
        List<Map<String, String>> movedNodes = new ArrayList<>();

        for (Map.Entry<String, String> entry : nextNodes.entrySet()) {
            String path    = entry.getKey();
            String cluster = entry.getValue();
            if (!prevNodes.containsKey(path)) {
                addedNodes.add(path);
            } else if (!cluster.equals(prevNodes.get(path))) {
                // Same file but different cluster → moved
                Map<String, String> move = new HashMap<>();
                move.put("file", path);
                move.put("from_cluster", prevNodes.get(path));
                move.put("to_cluster", cluster);
                movedNodes.add(move);
                modifiedNodes.add(path);
            }
        }
        for (String path : prevNodes.keySet()) {
            if (!nextNodes.containsKey(path)) removedNodes.add(path);
        }

        Map<String, Object> delta = new HashMap<>();
        delta.put("added_clusters",   addedClusters);
        delta.put("removed_clusters", removedClusters);
        delta.put("added_nodes",      addedNodes);
        delta.put("removed_nodes",    removedNodes);
        delta.put("modified_nodes",   modifiedNodes);
        delta.put("moved_nodes",      movedNodes);

        try {
            return objectMapper.writeValueAsString(delta);
        } catch (Exception e) {
            log.warn("[DELTA] Serialization failed", e);
            return "{}";
        }
    }

    private Set<String> clusterIds(GraphBlueprintDto blueprint) {
        Set<String> ids = new HashSet<>();
        if (blueprint.getClusters() != null) {
            blueprint.getClusters().forEach(c -> ids.add(c.getId()));
        }
        return ids;
    }

    private Map<String, String> nodeClusterMap(GraphBlueprintDto blueprint) {
        Map<String, String> map = new HashMap<>();
        if (blueprint.getNodes() != null) {
            blueprint.getNodes().forEach(n -> map.put(n.getCanonicalPath(), n.getClusterId()));
        }
        return map;
    }
}
