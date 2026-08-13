package com.codesight.codesight.app.project.controllers.graph;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.graph.ClusterOverrideDto;
import com.codesight.codesight.app.project.dto.graph.ClusterOverrideRequest;
import com.codesight.codesight.app.project.dto.graph.OverrideResponse;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.services.ProjectAccessService;
import com.codesight.codesight.app.project.services.graph.ClusterOverrideService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * Cluster name/summary override — lets an ADMIN or OWNER replace an LLM-suggested cluster
 * label (SRS 2.2.9). Gated at ADMIN to match the SRS's "any ADMIN or OWNER" wording; the
 * lighter-weight MEMBER-tier "cluster notes" feature is a separate, not-yet-built annotation
 * type and is not exposed by this endpoint.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/graph/overrides")
@RequiredArgsConstructor
public class ClusterOverrideController {

    private final ClusterOverrideService clusterOverrideService;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    @PutMapping("/cluster")
    public ResponseEntity<OverrideResponse> upsertClusterOverride(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody ClusterOverrideRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.ADMIN);

        log.info("[CONTROLLER] Cluster override upsert — project={} cluster={} user={}",
                projectId, request.getClusterId(), currentUser.getId());

        return ResponseEntity.ok(
                clusterOverrideService.upsertOverride(projectId, request, currentUser.getId())
        );
    }

    @GetMapping
    public ResponseEntity<List<ClusterOverrideDto>> listOverrides(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam UUID snapshotId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());

        return ResponseEntity.ok(clusterOverrideService.listOverrides(projectId, snapshotId));
    }
}
