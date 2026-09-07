package com.codesight.codesight.app.project.controllers.graph;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.graph.ClusterNoteDto;
import com.codesight.codesight.app.project.dto.graph.ClusterNoteRequest;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.services.ProjectAccessService;
import com.codesight.codesight.app.project.services.graph.ClusterNoteService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * Collaborative cluster notes (SRS 2.2.9) — a free-form, timestamped, authored
 * annotation any project member holding at least MEMBER can attach to a
 * cluster. Deliberately separate from {@link ClusterOverrideController}, which
 * is gated to ADMIN/OWNER and replaces the cluster's name/summary in place;
 * notes accumulate instead of overwriting each other, so VIEWER can read them
 * here but write access starts one tier below the override endpoint.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/graph/notes")
@RequiredArgsConstructor
public class ClusterNoteController {

    private final ClusterNoteService clusterNoteService;
    private final OrganizationAccessService organizationAccessService;
    private final ProjectAccessService projectAccessService;

    @PostMapping
    public ResponseEntity<ClusterNoteDto> addNote(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody ClusterNoteRequest request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.MEMBER);

        log.info("[CONTROLLER] Cluster note added — project={} cluster={} user={}",
                projectId, request.getClusterId(), currentUser.getId());

        return ResponseEntity.ok(
                clusterNoteService.addNote(projectId, request, currentUser.getId())
        );
    }

    @GetMapping
    public ResponseEntity<List<ClusterNoteDto>> listNotes(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam UUID snapshotId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireMembership(projectId, currentUser.getId());

        return ResponseEntity.ok(clusterNoteService.listNotes(projectId, snapshotId));
    }

    @DeleteMapping("/{noteId}")
    public ResponseEntity<Void> deleteNote(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @PathVariable Long noteId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationAccessService.requireMembership(organizationId, currentUser.getId());
        projectAccessService.requireRole(projectId, currentUser.getId(), ProjectMemberRole.MEMBER);

        clusterNoteService.deleteNote(projectId, noteId, currentUser.getId());

        return ResponseEntity.noContent().build();
    }
}
