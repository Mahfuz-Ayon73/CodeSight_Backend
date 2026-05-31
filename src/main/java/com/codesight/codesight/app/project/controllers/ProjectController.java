package com.codesight.codesight.app.project.controllers;

import com.codesight.codesight.app.project.dto.GithubUploadRequestDto;
import com.codesight.codesight.app.project.dto.ProjectRequestDto;
import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.services.ProjectService;
import com.codesight.codesight.app.project.services.ProjectUploadService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/organizations/{organizationId}/projects")
@RequiredArgsConstructor
public class ProjectController {

    private final ProjectService projectService;
    private final ProjectUploadService projectUploadService;

    @PostMapping
    public ResponseEntity<ProjectResponseDto> createProject(
            @PathVariable UUID organizationId,
            @Valid @RequestBody ProjectRequestDto request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(projectService.createProject(organizationId, request, currentUser.getId()));
    }

    @GetMapping
    public ResponseEntity<List<ProjectResponseDto>> listProjects(
            @PathVariable UUID organizationId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(projectService.listProjects(organizationId, currentUser.getId()));
    }

    @GetMapping("/{projectId}")
    public ResponseEntity<ProjectResponseDto> getProject(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(projectService.getProject(organizationId, projectId, currentUser.getId()));
    }

    @DeleteMapping("/{projectId}")
    public ResponseEntity<Void> deleteProject(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        projectService.deleteProject(organizationId, projectId, currentUser.getId());
        return ResponseEntity.noContent().build();
    }

    @PostMapping(value = "/{projectId}/upload/zip", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<ProjectResponseDto> uploadZip(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestPart("file") MultipartFile file,
            @AuthenticationPrincipal UserModel currentUser
    ) throws IOException {
        return ResponseEntity.ok(
                projectUploadService.uploadZip(organizationId, projectId, currentUser.getId(), file)
        );
    }

    /**
     * Upload a source folder from the browser. Use {@code <input type="file" webkitdirectory directory multiple />}
     * so each part keeps its relative path in the original filename (e.g. {@code src/app/page.tsx}).
     */
    @PostMapping(value = "/{projectId}/upload/folder", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<ProjectResponseDto> uploadFolder(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @RequestParam("files") List<MultipartFile> files,
            @AuthenticationPrincipal UserModel currentUser
    ) throws IOException {
        return ResponseEntity.ok(
                projectUploadService.uploadFolder(organizationId, projectId, currentUser.getId(), files)
        );
    }

    @PostMapping("/{projectId}/upload/github")
    public ResponseEntity<ProjectResponseDto> uploadGithub(
            @PathVariable UUID organizationId,
            @PathVariable UUID projectId,
            @Valid @RequestBody GithubUploadRequestDto request,
            @AuthenticationPrincipal UserModel currentUser
    ) throws IOException {
        return ResponseEntity.ok(
                projectUploadService.uploadFromGithub(
                        organizationId,
                        projectId,
                        currentUser.getId(),
                        request.getGithubUrl()
                )
        );
    }
}
