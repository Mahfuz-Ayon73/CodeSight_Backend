package com.codesight.codesight.app.project.controllers.graph;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.BlueprintDto;
import com.codesight.codesight.app.project.dto.graph.CommitDiffDto;
import com.codesight.codesight.app.project.dto.graph.CommitHistoryResponse;
import com.codesight.codesight.app.project.dto.graph.SnapshotSummaryDto;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.app.project.services.ProjectAccessService;
import com.codesight.codesight.app.project.services.git.CommitHistoryService;
import com.codesight.codesight.app.project.services.git.HistoricalAnalysisService;
import com.codesight.codesight.app.project.services.graph.SnapshotBlueprintService;
import com.codesight.codesight.app.user.model.UserModel;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * Two-Phase Commit History: Phase-1 timeline/diff data (git-only, no re-analysis) and the
 * trigger for Phase-2 deep re-analysis of historical commits. Deep re-analysis is dispatched
 * via the external {@code historicalAnalysisService} bean call (not a self-invocation) so its
 * {@code @Async} annotation is honoured by the Spring proxy.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}")
@RequiredArgsConstructor
public class GraphHistoryController {

    private final CommitHistoryService commitHistoryService;
    private final HistoricalAnalysisService historicalAnalysisService;
    private final SnapshotBlueprintService snapshotBlueprintService;
    private final GraphSnapshotRepository graphSnapshotRepository;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    @GetMapping("/commits")
    public ResponseEntity<CommitHistoryResponse> getCommits(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam(defaultValue = "10") int count,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());

        List<CommitDiffDto> commits = commitHistoryService.getLastNCommits(organizationId, projectId, count);
        List<SnapshotSummaryDto> snapshots = graphSnapshotRepository
                .findByProjectIdOrderByAnalyzedAtDesc(projectId)
                .stream()
                .map(GraphHistoryController::toSnapshotSummary)
                .toList();

        return ResponseEntity.ok(
                CommitHistoryResponse.builder()
                        .projectId(projectId)
                        .commits(commits)
                        .snapshots(snapshots)
                        .build()
        );
    }

    @PostMapping("/analyze-history")
    public ResponseEntity<Void> analyzeHistory(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam(defaultValue = "10") int count,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.ADMIN);

        log.info("[CONTROLLER] Deep re-analysis triggered — org={} project={} count={} user={}",
                organizationId, projectId, count, currentUser.getId());
        historicalAnalysisService.analyzeHistory(organizationId, projectId, count);
        return ResponseEntity.accepted().build();
    }

    @GetMapping("/snapshots/{snapshotId}/blueprint")
    public ResponseEntity<BlueprintDto> getSnapshotBlueprint(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @PathVariable UUID snapshotId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());

        return ResponseEntity.ok(
                snapshotBlueprintService.getSnapshotBlueprint(organizationId, projectId, snapshotId)
        );
    }

    /**
     * Most recently analyzed snapshot for this project — live analyses persist one via
     * {@code PythonAnalysisService.persistLiveSnapshot}, historical re-analyses via
     * {@code HistoricalAnalysisService}. The frontend uses this to resolve a snapshotId
     * to attach cluster overrides to when viewing the default (non-historical) canvas.
     * 404 if the project has never completed an analysis since this feature shipped.
     */
    @GetMapping("/snapshots/latest")
    public ResponseEntity<SnapshotSummaryDto> getLatestSnapshot(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());

        return graphSnapshotRepository.findFirstByProjectIdOrderByAnalyzedAtDesc(projectId)
                .map(GraphHistoryController::toSnapshotSummary)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    private static SnapshotSummaryDto toSnapshotSummary(GraphSnapshot snapshot) {
        String sha = snapshot.getCommitSha();
        return SnapshotSummaryDto.builder()
                .snapshotId(snapshot.getId())
                .commitSha(sha)
                .shortSha(sha != null ? sha.substring(0, Math.min(7, sha.length())) : null)
                .commitMessage(snapshot.getCommitMessage())
                .commitAuthor(snapshot.getCommitAuthor())
                .committedAt(snapshot.getCommittedAt())
                .analyzedAt(snapshot.getAnalyzedAt())
                .isAnalyzed(!Boolean.TRUE.equals(snapshot.getInProgress()))
                .deltaJson(snapshot.getDeltaJson())
                .nodesCount(snapshot.getNodesCount())
                .edgesCount(snapshot.getEdgesCount())
                .clustersCount(snapshot.getClustersCount())
                .build();
    }
}
