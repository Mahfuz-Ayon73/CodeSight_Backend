package com.codesight.codesight.app.project.controllers;

import com.codesight.codesight.app.project.dto.InviteProjectMemberRequestDto;
import com.codesight.codesight.app.project.dto.ProjectMemberResponseDto;
import com.codesight.codesight.app.project.dto.UpdateProjectMemberRoleRequestDto;
import com.codesight.codesight.app.project.services.ProjectMemberService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/members")
@RequiredArgsConstructor
public class ProjectMemberController {

    private final ProjectMemberService projectMemberService;

    @PostMapping
    public ResponseEntity<ProjectMemberResponseDto> inviteMember(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody InviteProjectMemberRequestDto request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(projectMemberService.inviteMember(organizationId, projectId, currentUser.getId(), request));
    }

    @GetMapping
    public ResponseEntity<List<ProjectMemberResponseDto>> listMembers(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(
                projectMemberService.listMembers(organizationId, projectId, currentUser.getId()));
    }

    @PatchMapping("/{userId}/role")
    public ResponseEntity<ProjectMemberResponseDto> updateMemberRole(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @PathVariable UUID userId,
            @Valid @RequestBody UpdateProjectMemberRoleRequestDto request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(
                projectMemberService.updateMemberRole(organizationId, projectId, userId, currentUser.getId(), request));
    }

    @DeleteMapping("/{userId}")
    public ResponseEntity<Void> removeMember(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @PathVariable UUID userId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        projectMemberService.removeMember(organizationId, projectId, userId, currentUser.getId());
        return ResponseEntity.noContent().build();
    }
}
