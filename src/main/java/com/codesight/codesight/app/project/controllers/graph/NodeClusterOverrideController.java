package com.codesight.codesight.app.project.controllers.graph;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.graph.NodeClusterOverrideDto;
import com.codesight.codesight.app.project.dto.graph.NodeMoveEvaluationDto;
import com.codesight.codesight.app.project.dto.graph.NodeMovePreviewRequest;
import com.codesight.codesight.app.project.dto.graph.NodeOverrideRequest;
import com.codesight.codesight.app.project.dto.graph.OverrideResponse;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.services.ProjectAccessService;
import com.codesight.codesight.app.project.services.graph.NodeClusterOverrideService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/** File-to-cluster move preview and persistence for one immutable graph snapshot. */
@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/graph/overrides/nodes")
@RequiredArgsConstructor
public class NodeClusterOverrideController {

    private final NodeClusterOverrideService nodeClusterOverrideService;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    @PostMapping("/preview")
    public ResponseEntity<NodeMoveEvaluationDto> previewMove(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody NodeMovePreviewRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());
        return ResponseEntity.ok(nodeClusterOverrideService.previewMove(projectId, request));
    }

    @PutMapping
    public ResponseEntity<OverrideResponse> upsertOverride(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody NodeOverrideRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.ADMIN);
        return ResponseEntity.ok(
                nodeClusterOverrideService.upsertOverride(projectId, request, currentUser.getId()));
    }

    @GetMapping
    public ResponseEntity<List<NodeClusterOverrideDto>> listOverrides(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam UUID snapshotId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());
        return ResponseEntity.ok(nodeClusterOverrideService.listOverrides(projectId, snapshotId));
    }
}
