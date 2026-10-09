package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.NodeClusterOverrideDto;
import com.codesight.codesight.app.project.dto.graph.NodeMoveEvaluationDto;
import com.codesight.codesight.app.project.dto.graph.NodeMovePreviewRequest;
import com.codesight.codesight.app.project.dto.graph.NodeOverrideRequest;
import com.codesight.codesight.app.project.dto.graph.OverrideResponse;
import com.codesight.codesight.app.project.model.graph.GraphEdge;
import com.codesight.codesight.app.project.model.graph.GraphNode;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.model.graph.NodeClusterOverride;
import com.codesight.codesight.app.project.repository.graph.GraphEdgeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphNodeRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.app.project.repository.graph.NodeClusterOverrideRepository;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.ConflictException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * Evaluates and persists snapshot-local file placement overrides. The canonical
 * analyzer blueprint and dependency edges are never mutated.
 */
@Service
@RequiredArgsConstructor
public class NodeClusterOverrideService {

    private static final double EPSILON = 1.0e-9;
    private static final double VERDICT_THRESHOLD = 0.10;

    private final NodeClusterOverrideRepository overrideRepository;
    private final GraphSnapshotRepository snapshotRepository;
    private final GraphNodeRepository nodeRepository;
    private final GraphEdgeRepository edgeRepository;

    @Transactional(readOnly = true)
    public NodeMoveEvaluationDto previewMove(UUID projectId, NodeMovePreviewRequest request) {
        validateSnapshot(projectId, request.getSnapshotId());

        List<GraphNode> nodes = nodeRepository.findBySnapshotId(request.getSnapshotId());
        if (nodes.isEmpty()) {
            throw new BadRequestException("This snapshot is not materialized, so file moves cannot be evaluated");
        }

        GraphNode movedNode = nodes.stream()
                .filter(node -> node.getFilePath().equals(request.getFilePath()))
                .findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("File not found in snapshot"));

        List<NodeClusterOverride> overrides = overrideRepository.findBySnapshotId(request.getSnapshotId());
        Map<Long, String> memberships = effectiveMemberships(nodes, overrides);
        String fromClusterId = memberships.get(movedNode.getId());
        String targetClusterId = request.getTargetClusterId();

        Set<String> validClusters = new HashSet<>();
        nodes.forEach(node -> validClusters.add(node.getClusterId()));
        overrides.forEach(override -> validClusters.add(override.getOverrideClusterId()));
        if (!validClusters.contains(targetClusterId)) {
            throw new BadRequestException("Target cluster does not exist in this snapshot");
        }
        if (targetClusterId.equals(fromClusterId)) {
            throw new BadRequestException("File is already assigned to the target cluster");
        }

        List<GraphEdge> edges = edgeRepository.findBySnapshotId(request.getSnapshotId());
        PartitionMetrics before = calculatePartitionMetrics(nodes, edges, memberships);
        LocalPlacement beforePlacement = calculateFilePlacement(movedNode.getId(), edges, memberships);

        Map<Long, String> proposedMemberships = new HashMap<>(memberships);
        proposedMemberships.put(movedNode.getId(), targetClusterId);
        PartitionMetrics after = calculatePartitionMetrics(nodes, edges, proposedMemberships);
        LocalPlacement afterPlacement = calculateFilePlacement(movedNode.getId(), edges, proposedMemberships);

        double scoreBefore = combinedScore(before, beforePlacement);
        double scoreAfter = combinedScore(after, afterPlacement);
        double scoreDelta = scoreAfter - scoreBefore;
        String verdict = scoreDelta > VERDICT_THRESHOLD
                ? "IMPROVES"
                : scoreDelta < -VERDICT_THRESHOLD ? "WORSENS" : "NEUTRAL";

        Map<String, Integer> beforeSizes = clusterSizes(memberships);
        Map<String, Integer> afterSizes = clusterSizes(proposedMemberships);

        return NodeMoveEvaluationDto.builder()
                .snapshotId(request.getSnapshotId())
                .filePath(request.getFilePath())
                .fromClusterId(fromClusterId)
                .toClusterId(targetClusterId)
                .verdict(verdict)
                .qualityScore(metric(scoreBefore, scoreAfter))
                .modularity(metric(before.modularity(), after.modularity()))
                .cohesion(metric(before.cohesion(), after.cohesion()))
                .coupling(metric(before.coupling(), after.coupling()))
                .sizeBalance(metric(before.sizeBalance(), after.sizeBalance()))
                .filePlacement(metric(beforePlacement.score(), afterPlacement.score()))
                .clusterSizes(NodeMoveEvaluationDto.ClusterSizeDelta.builder()
                        .sourceBefore(beforeSizes.getOrDefault(fromClusterId, 0))
                        .sourceAfter(afterSizes.getOrDefault(fromClusterId, 0))
                        .targetBefore(beforeSizes.getOrDefault(targetClusterId, 0))
                        .targetAfter(afterSizes.getOrDefault(targetClusterId, 0))
                        .build())
                .reasons(buildReasons(before, after, beforePlacement, afterPlacement))
                .methodology("Quality combines graph modularity (55%), internal-edge cohesion (35%), "
                        + "and cluster-size balance (10%); when the file has weighted dependency edges, "
                        + "75% of that graph score is combined with 25% file-to-cluster placement fit.")
                .build();
    }

    @Transactional
    public OverrideResponse upsertOverride(UUID projectId, NodeOverrideRequest request, UUID userId) {
        validateSnapshot(projectId, request.getSnapshotId());

        GraphNode node = nodeRepository
                .findBySnapshotIdAndFilePath(request.getSnapshotId(), request.getFilePath())
                .orElseThrow(() -> new ResourceNotFoundException("File not found in snapshot"));

        boolean targetExists = nodeRepository.existsBySnapshotIdAndClusterId(
                request.getSnapshotId(), request.getOverrideClusterId());
        if (!targetExists) {
            throw new BadRequestException("Target cluster does not exist in this snapshot");
        }

        Optional<NodeClusterOverride> existingOpt = overrideRepository
                .findBySnapshotIdAndFilePath(request.getSnapshotId(), request.getFilePath());

        NodeClusterOverride override;
        if (existingOpt.isPresent()) {
            override = existingOpt.get();
            if (request.getExpectedVersion() != null
                    && !request.getExpectedVersion().equals(override.getVersion())) {
                throw new ConflictException("This file placement was edited by someone else — refresh and try again");
            }
            override.setOverrideClusterId(request.getOverrideClusterId());
            override.setEditedBy(userId);
        } else {
            if (request.getExpectedVersion() != null) {
                throw new ConflictException("File placement override no longer exists — refresh and try again");
            }
            override = NodeClusterOverride.builder()
                    .projectId(projectId)
                    .snapshotId(request.getSnapshotId())
                    .filePath(request.getFilePath())
                    .originalClusterId(node.getClusterId())
                    .overrideClusterId(request.getOverrideClusterId())
                    .editedBy(userId)
                    .build();
        }

        NodeClusterOverride saved = overrideRepository.save(override);
        return OverrideResponse.builder()
                .id(saved.getId())
                .version(saved.getVersion())
                .snapshotId(saved.getSnapshotId())
                .editedBy(saved.getEditedBy().toString())
                .editedAt(saved.getEditedAt())
                .build();
    }

    @Transactional(readOnly = true)
    public List<NodeClusterOverrideDto> listOverrides(UUID projectId, UUID snapshotId) {
        validateSnapshot(projectId, snapshotId);
        return overrideRepository.findBySnapshotId(snapshotId).stream()
                .map(override -> NodeClusterOverrideDto.builder()
                        .filePath(override.getFilePath())
                        .originalClusterId(override.getOriginalClusterId())
                        .overrideClusterId(override.getOverrideClusterId())
                        .version(override.getVersion())
                        .build())
                .toList();
    }

    private void validateSnapshot(UUID projectId, UUID snapshotId) {
        GraphSnapshot snapshot = snapshotRepository.findById(snapshotId)
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));
        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }
    }

    private Map<Long, String> effectiveMemberships(
            List<GraphNode> nodes,
            List<NodeClusterOverride> overrides
    ) {
        Map<String, String> overrideByPath = new HashMap<>();
        overrides.forEach(override -> overrideByPath.put(
                override.getFilePath(), override.getOverrideClusterId()));

        Map<Long, String> memberships = new HashMap<>();
        for (GraphNode node : nodes) {
            memberships.put(node.getId(),
                    overrideByPath.getOrDefault(node.getFilePath(), node.getClusterId()));
        }
        return memberships;
    }

    private PartitionMetrics calculatePartitionMetrics(
            List<GraphNode> nodes,
            List<GraphEdge> edges,
            Map<Long, String> memberships
    ) {
        double totalWeight = 0.0;
        double internalWeight = 0.0;
        Map<Long, Double> degreeByNode = new HashMap<>();
        Map<String, Double> internalByCluster = new HashMap<>();

        for (GraphEdge edge : edges) {
            double weight = positiveWeight(edge.getWeight());
            if (weight <= 0 || !memberships.containsKey(edge.getSourceNodeId())
                    || !memberships.containsKey(edge.getTargetNodeId())) {
                continue;
            }
            totalWeight += weight;
            degreeByNode.merge(edge.getSourceNodeId(), weight, Double::sum);
            degreeByNode.merge(edge.getTargetNodeId(), weight, Double::sum);

            String sourceCluster = memberships.get(edge.getSourceNodeId());
            String targetCluster = memberships.get(edge.getTargetNodeId());
            if (sourceCluster.equals(targetCluster)) {
                internalWeight += weight;
                internalByCluster.merge(sourceCluster, weight, Double::sum);
            }
        }

        double modularity = 0.0;
        if (totalWeight > EPSILON) {
            Map<String, Double> degreeByCluster = new HashMap<>();
            for (Map.Entry<Long, Double> entry : degreeByNode.entrySet()) {
                degreeByCluster.merge(memberships.get(entry.getKey()), entry.getValue(), Double::sum);
            }
            Set<String> clusters = new HashSet<>(memberships.values());
            for (String cluster : clusters) {
                double internalFraction = internalByCluster.getOrDefault(cluster, 0.0) / totalWeight;
                double degreeFraction = degreeByCluster.getOrDefault(cluster, 0.0) / (2.0 * totalWeight);
                modularity += internalFraction - degreeFraction * degreeFraction;
            }
        }

        double cohesion = totalWeight > EPSILON ? internalWeight / totalWeight * 100.0 : 0.0;
        double coupling = totalWeight > EPSILON ? (totalWeight - internalWeight) / totalWeight * 100.0 : 0.0;
        double sizeBalance = sizeBalance(memberships, nodes.size());
        double graphScore = 55.0 * normalizedModularity(modularity)
                + 0.35 * cohesion
                + 0.10 * sizeBalance;

        return new PartitionMetrics(modularity, cohesion, coupling, sizeBalance, graphScore);
    }

    private LocalPlacement calculateFilePlacement(
            Long nodeId,
            List<GraphEdge> edges,
            Map<Long, String> memberships
    ) {
        String clusterId = memberships.get(nodeId);
        double incidentWeight = 0.0;
        double internalWeight = 0.0;
        for (GraphEdge edge : edges) {
            double weight = positiveWeight(edge.getWeight());
            if (weight <= 0) continue;
            Long neighbor = null;
            if (nodeId.equals(edge.getSourceNodeId())) neighbor = edge.getTargetNodeId();
            else if (nodeId.equals(edge.getTargetNodeId())) neighbor = edge.getSourceNodeId();
            if (neighbor == null || !memberships.containsKey(neighbor)) continue;

            incidentWeight += weight;
            if (clusterId.equals(memberships.get(neighbor))) internalWeight += weight;
        }
        return incidentWeight > EPSILON
                ? new LocalPlacement(internalWeight / incidentWeight * 100.0, true)
                : new LocalPlacement(0.0, false);
    }

    private double combinedScore(PartitionMetrics metrics, LocalPlacement placement) {
        return placement.hasEdges()
                ? metrics.graphScore() * 0.75 + placement.score() * 0.25
                : metrics.graphScore();
    }

    private double sizeBalance(Map<Long, String> memberships, int nodeCount) {
        if (nodeCount <= 1) return 100.0;
        Map<String, Integer> sizes = clusterSizes(memberships);
        if (sizes.size() <= 1) return 0.0;

        double entropy = 0.0;
        for (int size : sizes.values()) {
            double probability = (double) size / nodeCount;
            entropy -= probability * Math.log(probability);
        }
        return entropy / Math.log(sizes.size()) * 100.0;
    }

    private Map<String, Integer> clusterSizes(Map<Long, String> memberships) {
        Map<String, Integer> sizes = new HashMap<>();
        memberships.values().forEach(cluster -> sizes.merge(cluster, 1, Integer::sum));
        return sizes;
    }

    private List<String> buildReasons(
            PartitionMetrics before,
            PartitionMetrics after,
            LocalPlacement beforePlacement,
            LocalPlacement afterPlacement
    ) {
        List<String> reasons = new ArrayList<>();
        if (beforePlacement.hasEdges()) {
            double delta = afterPlacement.score() - beforePlacement.score();
            reasons.add(delta >= 0
                    ? String.format("File dependency fit improves by %.2f percentage points", delta)
                    : String.format("File dependency fit decreases by %.2f percentage points", -delta));
        } else {
            reasons.add("The file has no weighted dependency edges, so placement fit is unavailable");
        }

        double modularityDelta = after.modularity() - before.modularity();
        reasons.add(modularityDelta >= 0
                ? String.format("Graph modularity improves by %.4f", modularityDelta)
                : String.format("Graph modularity decreases by %.4f", -modularityDelta));

        double cohesionDelta = after.cohesion() - before.cohesion();
        reasons.add(cohesionDelta >= 0
                ? String.format("Internal-edge cohesion improves by %.2f percentage points", cohesionDelta)
                : String.format("Internal-edge cohesion decreases by %.2f percentage points", -cohesionDelta));

        double balanceDelta = after.sizeBalance() - before.sizeBalance();
        if (Math.abs(balanceDelta) >= 0.01) {
            reasons.add(balanceDelta >= 0
                    ? String.format("Cluster-size balance improves by %.2f percentage points", balanceDelta)
                    : String.format("Cluster-size balance decreases by %.2f percentage points", -balanceDelta));
        }
        return reasons;
    }

    private NodeMoveEvaluationDto.MetricDelta metric(double before, double after) {
        return NodeMoveEvaluationDto.MetricDelta.builder()
                .before(round(before))
                .after(round(after))
                .delta(round(after - before))
                .build();
    }

    private double normalizedModularity(double modularity) {
        return (Math.max(-1.0, Math.min(1.0, modularity)) + 1.0) / 2.0;
    }

    private double positiveWeight(Double weight) {
        return weight != null && weight > 0 ? weight : 0.0;
    }

    private double round(double value) {
        return Math.round(value * 10_000.0) / 10_000.0;
    }

    private record PartitionMetrics(
            double modularity,
            double cohesion,
            double coupling,
            double sizeBalance,
            double graphScore
    ) {}

    private record LocalPlacement(double score, boolean hasEdges) {}
}
