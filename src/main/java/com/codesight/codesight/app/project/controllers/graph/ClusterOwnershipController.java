package com.codesight.codesight.app.project.controllers.graph;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.graph.OwnershipRequest;
import com.codesight.codesight.app.project.dto.graph.OwnershipResponse;
import com.codesight.codesight.app.project.services.ProjectAccessService;
import com.codesight.codesight.app.project.services.git.ClusterOwnershipService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * Git-blame-based cluster ownership — "who currently owns this code", as
 * opposed to {@link GraphHistoryController}'s commit-log timeline. POST (not
 * GET) because the request carries the full list of canonical paths the
 * frontend wants blamed, which can run into the hundreds and doesn't belong
 * in a query string. Read-only, so MEMBER-tier access (same floor as commit
 * history) rather than the ADMIN tier used by cluster overrides.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/graph/ownership")
@RequiredArgsConstructor
public class ClusterOwnershipController {

    private final ClusterOwnershipService clusterOwnershipService;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    @PostMapping
    public ResponseEntity<OwnershipResponse> getOwnership(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody OwnershipRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());

        log.info("[CONTROLLER] Ownership requested — project={} files={} user={}",
                projectId, request.getPaths().size(), currentUser.getId());

        return ResponseEntity.ok(
                clusterOwnershipService.computeOwnership(organizationId, projectId, request.getPaths())
        );
    }
}
