package com.codesight.codesight.app.project.controllers.graph;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.graph.GraphEditRevisionCreateRequest;
import com.codesight.codesight.app.project.dto.graph.GraphEditRevisionDto;
import com.codesight.codesight.app.project.dto.graph.GraphEditRevisionUpdateRequest;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.services.ProjectAccessService;
import com.codesight.codesight.app.project.services.graph.GraphEditRevisionService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/graph/edit-revisions")
@RequiredArgsConstructor
public class GraphEditRevisionController {

    private final GraphEditRevisionService revisionService;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    @GetMapping
    public ResponseEntity<List<GraphEditRevisionDto>> list(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam UUID snapshotId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());
        return ResponseEntity.ok(revisionService.list(projectId, snapshotId));
    }

    @PostMapping
    public ResponseEntity<GraphEditRevisionDto> create(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody GraphEditRevisionCreateRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.MEMBER);
        return ResponseEntity.ok(revisionService.create(projectId, request, currentUser.getId()));
    }

    @PutMapping("/{revisionId}")
    public ResponseEntity<GraphEditRevisionDto> update(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @PathVariable UUID revisionId,
            @Valid @RequestBody GraphEditRevisionUpdateRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.MEMBER);
        return ResponseEntity.ok(revisionService.update(projectId, revisionId, request, currentUser.getId()));
    }

    @DeleteMapping("/{revisionId}")
    public ResponseEntity<Void> delete(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @PathVariable UUID revisionId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.MEMBER);
        revisionService.delete(projectId, revisionId);
        return ResponseEntity.noContent().build();
    }
}
