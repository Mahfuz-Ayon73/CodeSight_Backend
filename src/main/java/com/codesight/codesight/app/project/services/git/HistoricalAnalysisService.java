package com.codesight.codesight.app.project.services.git;

import com.codesight.codesight.app.project.dto.AnalysisRequestDto;
import com.codesight.codesight.app.project.dto.AnalysisResponseDto;
import com.codesight.codesight.app.project.dto.graph.CommitDiffDto;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.app.project.services.graph.GraphDeltaService;
import com.codesight.codesight.app.project.services.graph.SnapshotPersistenceService;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.ObjectLoader;
import org.eclipse.jgit.lib.Repository;
import org.eclipse.jgit.revwalk.RevCommit;
import org.eclipse.jgit.revwalk.RevTree;
import org.eclipse.jgit.revwalk.RevWalk;
import org.eclipse.jgit.treewalk.TreeWalk;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class HistoricalAnalysisService {

    private final ProjectRepository projectRepository;
    private final GraphSnapshotRepository snapshotRepository;
    private final CommitHistoryService commitHistoryService;
    private final SnapshotPersistenceService snapshotPersistenceService;
    private final GraphDeltaService graphDeltaService;
    private final RestTemplate restTemplate;

    @Value("${codesight.python-analyzer.base-url:http://localhost:8000}")
    private String pythonAnalyzerBaseUrl;

    @Value("${codesight.analysis.output-dir:./storage/analysis}")
    private String analysisOutputDir;

    /**
     * Analyses the last {@code commitCount} commits for a project in the background.
     * Already-analysed commits (matched by SHA in GraphSnapshot) are skipped.
     */
    @Async
    public void analyzeHistory(UUID organizationId, UUID projectId, int commitCount) {
        log.info("[HISTORY-ANALYSIS] Starting history analysis for project {} ({} commits)", projectId, commitCount);

        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (project.getStoragePath() == null) {
            log.warn("[HISTORY-ANALYSIS] No storage path for project {}", projectId);
            return;
        }

        List<CommitDiffDto> commits = commitHistoryService.getLastNCommits(organizationId, projectId, commitCount);
        if (commits.isEmpty()) {
            log.info("[HISTORY-ANALYSIS] No commits found for project {}", projectId);
            return;
        }

        // Process commits from oldest to newest so delta can reference the previous snapshot
        List<CommitDiffDto> ordered = commits.reversed();

        String prevBlueprintPathStr = null;

        for (CommitDiffDto commit : ordered) {
            Optional<GraphSnapshot> existing = snapshotRepository.findByProjectIdAndCommitSha(projectId, commit.getSha());
            if (existing.isPresent()) {
                log.info("[HISTORY-ANALYSIS] Snapshot already exists for commit {} — skipping", commit.getShortSha());
                prevBlueprintPathStr = Paths.get(analysisOutputDir)
                        .resolve(organizationId.toString())
                        .resolve(projectId.toString())
                        .resolve(commit.getSha())
                        .resolve("graph_blueprint.json")
                        .toString();
                continue;
            }

            log.info("[HISTORY-ANALYSIS] Analysing commit {} ({})", commit.getShortSha(), commit.getMessage());

            Path tempRepoDir = null;
            try {
                tempRepoDir = extractCommitToTemp(project.getStoragePath(), commit.getSha(), projectId);
                if (tempRepoDir == null) {
                    log.warn("[HISTORY-ANALYSIS] Could not extract commit {} — skipping", commit.getShortSha());
                    continue;
                }

                Path outputDir = Paths.get(analysisOutputDir)
                        .resolve(organizationId.toString())
                        .resolve(projectId.toString())
                        .resolve(commit.getSha());
                Files.createDirectories(outputDir);

                // Call Python analyzer synchronously for this commit's files
                AnalysisResponseDto response = callAnalyzer(projectId, tempRepoDir, outputDir);
                if (response == null || !Boolean.TRUE.equals(response.getSuccess())) {
                    String err = response != null ? response.getErrorMessage() : "null response";
                    log.warn("[HISTORY-ANALYSIS] Analyzer failed for commit {}: {}", commit.getShortSha(), err);
                    continue;
                }

                Path blueprintPath = outputDir.resolve("graph_blueprint.json");
                if (!blueprintPath.toFile().exists()) {
                    log.warn("[HISTORY-ANALYSIS] Blueprint not found for commit {} at {}", commit.getShortSha(), blueprintPath);
                    continue;
                }

                // Persist snapshot
                UUID newSnapshotId = snapshotPersistenceService.persistSnapshot(
                        projectId, blueprintPath,
                        commit.getSha(), commit.getMessage(), commit.getAuthor(),
                        commit.getTimestamp()
                );

                // Compute delta vs previous snapshot
                if (prevBlueprintPathStr != null) {
                    Path prevBlueprint = Paths.get(prevBlueprintPathStr);
                    if (prevBlueprint.toFile().exists()) {
                        graphDeltaService.computeAndStoreDelta(newSnapshotId, prevBlueprint, blueprintPath);
                    }
                }

                prevBlueprintPathStr = blueprintPath.toString();

            } catch (Exception e) {
                log.error("[HISTORY-ANALYSIS] Error processing commit {} for project {}", commit.getShortSha(), projectId, e);
            } finally {
                if (tempRepoDir != null) {
                    deleteDirectory(tempRepoDir.toFile());
                }
            }
        }

        log.info("[HISTORY-ANALYSIS] Completed history analysis for project {}", projectId);
    }

    /**
     * Extracts all tracked files from a specific git commit into a temporary directory.
     * Returns the temp directory path, or null on failure.
     */
    private Path extractCommitToTemp(String repoPath, String commitSha, UUID projectId) {
        try {
            Path tempDir = Files.createTempDirectory("codesight-hist-" + projectId + "-");
            try (Git git = Git.open(new File(repoPath));
                 Repository repo = git.getRepository();
                 RevWalk walk = new RevWalk(repo)) {

                ObjectId commitId = repo.resolve(commitSha);
                if (commitId == null) {
                    log.warn("[HISTORY-ANALYSIS] Cannot resolve SHA {} in {}", commitSha, repoPath);
                    deleteDirectory(tempDir.toFile());
                    return null;
                }

                RevCommit commit = walk.parseCommit(commitId);
                RevTree tree = commit.getTree();

                try (TreeWalk treeWalk = new TreeWalk(repo)) {
                    treeWalk.addTree(tree);
                    treeWalk.setRecursive(true);

                    while (treeWalk.next()) {
                        String pathStr = treeWalk.getPathString();
                        // Skip .git and other non-source dirs
                        if (shouldSkip(pathStr)) continue;

                        ObjectId objectId = treeWalk.getObjectId(0);
                        ObjectLoader loader = repo.open(objectId);

                        Path targetFile = tempDir.resolve(pathStr);
                        Files.createDirectories(targetFile.getParent());
                        Files.write(targetFile, loader.getBytes());
                    }
                }
                return tempDir;
            }
        } catch (Exception e) {
            log.error("[HISTORY-ANALYSIS] Failed to extract commit {} to temp dir", commitSha, e);
            return null;
        }
    }

    private boolean shouldSkip(String path) {
        String lower = path.toLowerCase();
        return lower.startsWith("node_modules/")
                || lower.startsWith(".next/")
                || lower.startsWith("dist/")
                || lower.startsWith("build/")
                || lower.startsWith(".git/")
                || lower.startsWith(".turbo/")
                || lower.startsWith("coverage/")
                || lower.startsWith(".venv/")
                || lower.startsWith("__pycache__/")
                || lower.startsWith(".cache/");
    }

    private AnalysisResponseDto callAnalyzer(UUID projectId, Path repoPath, Path outputDir) {
        try {
            AnalysisRequestDto request = new AnalysisRequestDto();
            request.setProjectId(projectId.toString());
            request.setRepoPath(repoPath.toString());
            request.setOutputDir(outputDir.toString());
            request.setPurgeSource(false);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<AnalysisRequestDto> entity = new HttpEntity<>(request, headers);

            ResponseEntity<AnalysisResponseDto> response = restTemplate.postForEntity(
                    pythonAnalyzerBaseUrl + "/analyze",
                    entity,
                    AnalysisResponseDto.class
            );

            if (response.getStatusCode() == HttpStatus.OK) return response.getBody();
            log.warn("[HISTORY-ANALYSIS] Analyzer returned {}", response.getStatusCode());
            return null;
        } catch (Exception e) {
            log.error("[HISTORY-ANALYSIS] Analyzer call failed", e);
            return null;
        }
    }

    private void deleteDirectory(File dir) {
        if (dir == null || !dir.exists()) return;
        try {
            File[] files = dir.listFiles();
            if (files != null) {
                for (File f : files) {
                    if (f.isDirectory()) deleteDirectory(f);
                    else f.delete();
                }
            }
            dir.delete();
        } catch (Exception e) {
            log.warn("[HISTORY-ANALYSIS] Could not delete temp dir {}", dir, e);
        }
    }
}
