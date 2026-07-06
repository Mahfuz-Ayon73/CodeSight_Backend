package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.organization.services.OrganizationAccessService;
import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.model.ProjectSourceType;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class ProjectUploadService {

    private final ProjectRepository projectRepository;
    private final OrganizationAccessService organizationAccessService;
    private final CodebaseStorageService codebaseStorageService;
    private final ZipExtractService zipExtractService;
    private final FolderUploadService folderUploadService;
    private final GithubCloneService githubCloneService;
    private final PythonAnalysisService pythonAnalysisService;
    private final CloneProgressStore cloneProgressStore;

    @Transactional
    public ProjectResponseDto uploadZip(
            UUID organizationId,
            UUID projectId,
            UUID userId,
            MultipartFile file
    ) throws IOException {
        log.info("[ZIP] Upload started — org={} project={} user={} fileSize={}bytes filename={}",
                organizationId, projectId, userId,
                file != null ? file.getSize() : -1,
                file != null ? file.getOriginalFilename() : "null");

        ProjectModel project = loadProjectForUpload(organizationId, projectId, userId);
        log.info("[ZIP] Project loaded — status={}", project.getAnalysisStatus());

        Path repoPath = codebaseStorageService.resolveProjectRepoPath(organizationId, projectId);
        log.info("[ZIP] Repo path resolved — {}", repoPath);

        try {
            codebaseStorageService.prepareRepoDirectory(repoPath);
            log.info("[ZIP] Directory prepared — extracting ZIP...");

            zipExtractService.extractZip(file, repoPath);
            log.info("[ZIP] Extraction complete — marking success");

            markUploadSuccess(project, ProjectSourceType.LOCAL_ZIP, null, repoPath);
        } catch (IOException ex) {
            log.error("[ZIP] IOException during upload: {}", ex.getMessage(), ex);
            markUploadFailure(project, ex.getMessage());
            projectRepository.save(project);
            throw ex;
        } catch (RuntimeException ex) {
            log.error("[ZIP] RuntimeException during upload: {}", ex.getMessage(), ex);
            markUploadFailure(project, ex.getMessage());
            projectRepository.save(project);
            throw ex;
        }

        log.info("[ZIP] Upload finished successfully");
        return ObjectToDTOMapper.toProjectResponseDto(projectRepository.save(project));
    }

    @Transactional
    public ProjectResponseDto uploadFolder(
            UUID organizationId,
            UUID projectId,
            UUID userId,
            List<MultipartFile> files
    ) throws IOException {
        ProjectModel project = loadProjectForUpload(organizationId, projectId, userId);
        Path repoPath = codebaseStorageService.resolveProjectRepoPath(organizationId, projectId);

        try {
            codebaseStorageService.prepareRepoDirectory(repoPath);
            folderUploadService.saveFolderFiles(files, repoPath);
            markUploadSuccess(project, ProjectSourceType.LOCAL_FOLDER, null, repoPath);
        } catch (IOException ex) {
            markUploadFailure(project, ex.getMessage());
            projectRepository.save(project);
            throw ex;
        } catch (RuntimeException ex) {
            markUploadFailure(project, ex.getMessage());
            projectRepository.save(project);
            throw ex;
        }

        return ObjectToDTOMapper.toProjectResponseDto(projectRepository.save(project));
    }

    /**
     * Kick off a GitHub clone in the background and return immediately. Progress is
     * reported into CloneProgressStore (see GitCloneProgressMonitor) and polled by the
     * client via getCloneProgress. Runs on its own thread (@Async) rather than inside
     * one long DB transaction, since a large clone can take minutes and shouldn't hold
     * a DB connection open the whole time.
     */
    @Async
    public void startGithubUpload(
            UUID organizationId,
            UUID projectId,
            UUID userId,
            String githubUrl,
            String accessToken
    ) {
        String progressKey = projectId.toString();
        cloneProgressStore.update(progressKey, "connecting", 0, "Connecting to GitHub...");

        ProjectModel project;
        String normalizedUrl;
        try {
            project = loadProjectForUpload(organizationId, projectId, userId);
            normalizedUrl = githubCloneService.normalizeGithubUrl(githubUrl);
        } catch (Exception ex) {
            log.error("[GITHUB] Upload could not start — org={} project={}: {}",
                    organizationId, projectId, ex.getMessage(), ex);
            cloneProgressStore.update(progressKey, "failed", 0, ex.getMessage());
            return;
        }

        Path repoPath = codebaseStorageService.resolveProjectRepoPath(organizationId, projectId);

        try {
            cloneProgressStore.update(progressKey, "preparing", 0, "Preparing directory...");
            codebaseStorageService.prepareRepoDirectory(repoPath);

            GitCloneProgressMonitor monitor = new GitCloneProgressMonitor(cloneProgressStore, progressKey);
            githubCloneService.cloneRepository(normalizedUrl, repoPath, accessToken, monitor);

            markUploadSuccess(project, ProjectSourceType.GITHUB, normalizedUrl, repoPath);
            projectRepository.save(project);
            cloneProgressStore.update(progressKey, "done", 100, "Clone complete");
        } catch (Exception ex) {
            log.error("[GITHUB] Upload failed — org={} project={} url={}: {}",
                    organizationId, projectId, normalizedUrl, ex.getMessage(), ex);
            markUploadFailure(project, ex.getMessage());
            projectRepository.save(project);
            cloneProgressStore.update(progressKey, "failed", 0, ex.getMessage());
        }
    }

    public CloneProgressStore.CloneProgress getCloneProgress(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        return cloneProgressStore.get(projectId.toString());
    }

    public String getStoragePath(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        return projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new com.codesight.codesight.common.exception.ResourceNotFoundException("Project not found"))
                .getStoragePath();
    }

    private ProjectModel loadProjectForUpload(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        return projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
    }

    private void markUploadSuccess(
            ProjectModel project,
            ProjectSourceType sourceType,
            String githubUrl,
            Path repoPath
    ) {
        project.setSourceType(sourceType);
        project.setGithubUrl(githubUrl);
        project.setStoragePath(repoPath.toString());
        project.setAnalysisStatus(AnalysisStatus.READY_FOR_ANALYSIS);
        project.setUploadErrorMessage(null);
        project.setUploadedAt(LocalDateTime.now());
        // Analysis is now triggered manually by the user
    }

    private void markUploadFailure(ProjectModel project, String message) {
        project.setAnalysisStatus(AnalysisStatus.FAILED);
        project.setUploadErrorMessage(message);
    }

    @Transactional
    public ProjectResponseDto resetCodebase(UUID organizationId, UUID projectId, UUID userId) {
        organizationAccessService.requireMembership(organizationId, userId);
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new com.codesight.codesight.common.exception.ResourceNotFoundException("Project not found"));

        // Delete stored files if they exist
        if (project.getStoragePath() != null) {
            try {
                java.nio.file.Path repoPath = java.nio.file.Paths.get(project.getStoragePath());
                if (java.nio.file.Files.exists(repoPath)) {
                    java.nio.file.Files.walk(repoPath)
                        .sorted(java.util.Comparator.reverseOrder())
                        .map(java.nio.file.Path::toFile)
                        .forEach(java.io.File::delete);
                }
            } catch (Exception e) {
                log.warn("Failed to delete codebase files for project {}: {}", projectId, e.getMessage());
            }
        }

        project.setAnalysisStatus(AnalysisStatus.PENDING_UPLOAD);
        project.setStoragePath(null);
        project.setSourceType(ProjectSourceType.LOCAL_ZIP);
        project.setGithubUrl(null);
        project.setUploadedAt(null);
        project.setUploadErrorMessage(null);
        project.setAnalysisCompletedAt(null);

        return ObjectToDTOMapper.toProjectResponseDto(projectRepository.save(project));
    }
}
