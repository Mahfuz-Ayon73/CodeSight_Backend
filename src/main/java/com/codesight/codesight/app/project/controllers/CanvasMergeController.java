package com.codesight.codesight.app.project.controllers;

import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects/{projectId}/canvas")
@RequiredArgsConstructor
public class CanvasMergeController {

    private final ProjectRepository projectRepository;

    @GetMapping("/merges")
    public ResponseEntity<String> getMerges(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
        String merges = project.getUserMergesJson();
        return ResponseEntity.ok(merges != null ? merges : "[]");
    }

    @PutMapping("/merges")
    public ResponseEntity<Void> saveMerges(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestBody String mergesJson,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
        project.setUserMergesJson(mergesJson);
        projectRepository.save(project);
        return ResponseEntity.ok().build();
    }
}
