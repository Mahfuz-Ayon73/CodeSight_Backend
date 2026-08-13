package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.project.dto.AnalysisRequestDto;
import com.codesight.codesight.app.project.dto.AnalysisResponseDto;
import com.codesight.codesight.app.project.dto.AnalysisStatusResponseDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.app.project.services.graph.SnapshotPersistenceService;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.ResourceAccessException;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

@Slf4j
@Service
@RequiredArgsConstructor
public class PythonAnalysisService {

    private final ProjectRepository projectRepository;
    private final RestTemplate restTemplate;
    private final AnalysisProgressStore analysisProgressStore;
    private final SnapshotPersistenceService snapshotPersistenceService;

    @Value("${codesight.python-analyzer.base-url:http://localhost:8000}")
    private String pythonAnalyzerBaseUrl;

    @Value("${codesight.analysis.output-dir:/tmp/codesight-analysis}")
    private String analysisOutputDir;

    private static final long POLL_INTERVAL_MS = 2000;
    private static final int MAX_POLL_ATTEMPTS = 900; // ~30 minutes at 2s/poll
    private static final int MAX_CONSECUTIVE_POLL_ERRORS = 5;

    /**
     * Trigger analysis asynchronously after a successful codebase upload.
     * This method runs in the background and updates the project status.
     */
    @Async
    public CompletableFuture<Void> triggerAnalysisAsync(
            UUID organizationId,
            UUID projectId,
            Path repoPath
    ) {
        log.info("Starting async analysis for project {} in org {}", projectId, organizationId);
        
        try {
            // Update status to IN_PROGRESS
            updateProjectAnalysisStatus(organizationId, projectId, AnalysisStatus.IN_PROGRESS, null);
            
            // Create output directory for this project
            Path outputDir = Paths.get(analysisOutputDir)
                    .resolve(organizationId.toString())
                    .resolve(projectId.toString());
            
            // Build request
            AnalysisRequestDto request = new AnalysisRequestDto();
            request.setProjectId(projectId.toString());
            request.setRepoPath(repoPath.toString());
            request.setOutputDir(outputDir.toString());
            request.setPurgeSource(false); // Keep source files for now
            
            // Call Python FastAPI service — this only queues the job and returns
            // immediately; it does NOT mean the analysis has finished.
            AnalysisResponseDto response = callPythonAnalyzer(request);

            if (response.getSuccess() != null && response.getSuccess()) {
                // Queued successfully — poll Python's real task status until it
                // actually finishes (or fails/times out) before marking COMPLETED.
                pollUntilAnalysisFinishes(organizationId, projectId);
            } else {
                // Failed to even queue the analysis
                String errorMsg = response.getErrorMessage() != null
                    ? response.getErrorMessage()
                    : "Unknown analysis error";
                updateProjectAnalysisStatus(organizationId, projectId, AnalysisStatus.FAILED, errorMsg);
                log.error("Analysis failed for project {}: {}", projectId, errorMsg);
            }

        } catch (Exception e) {
            log.error("Analysis failed for project {} with exception", projectId, e);
            updateProjectAnalysisStatus(
                organizationId, 
                projectId, 
                AnalysisStatus.FAILED, 
                "Analysis service error: " + e.getMessage()
            );
        }
        
        return CompletableFuture.completedFuture(null);
    }

    /**
     * Synchronous analysis call for smaller codebases or testing.
     */
    public AnalysisResponseDto triggerAnalysisSync(
            UUID organizationId,
            UUID projectId,
            Path repoPath
    ) {
        log.info("Starting sync analysis for project {} in org {}", projectId, organizationId);
        
        // Create output directory
        Path outputDir = Paths.get(analysisOutputDir)
                .resolve(organizationId.toString())
                .resolve(projectId.toString());
        
        // Build request
        AnalysisRequestDto request = new AnalysisRequestDto();
        request.setProjectId(projectId.toString());
        request.setRepoPath(repoPath.toString());
        request.setOutputDir(outputDir.toString());
        request.setPurgeSource(false);
        
        try {
            return callPythonAnalyzer("/analyze/sync", request);
        } catch (Exception e) {
            log.error("Sync analysis failed for project {}", projectId, e);
            AnalysisResponseDto errorResponse = new AnalysisResponseDto();
            errorResponse.setSuccess(false);
            errorResponse.setProjectId(projectId.toString());
            errorResponse.setErrorMessage("Analysis service error: " + e.getMessage());
            return errorResponse;
        }
    }

    /**
     * Check if the Python analyzer service is healthy.
     */
    public boolean isAnalyzerHealthy() {
        try {
            ResponseEntity<String> response = restTemplate.getForEntity(
                pythonAnalyzerBaseUrl + "/health",
                String.class
            );
            return response.getStatusCode() == HttpStatus.OK;
        } catch (Exception e) {
            log.warn("Python analyzer health check failed: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Poll Python's real task status until the analysis completes, fails, or times out,
     * mirroring live stage/message into AnalysisProgressStore and only writing the terminal
     * status to the DB once Python actually reports it.
     */
    private void pollUntilAnalysisFinishes(UUID organizationId, UUID projectId) throws InterruptedException {
        String progressKey = projectId.toString();
        int consecutiveErrors = 0;

        for (int attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
            Thread.sleep(POLL_INTERVAL_MS);

            AnalysisStatusResponseDto status = fetchAnalysisStatus(projectId);
            if (status == null) {
                consecutiveErrors++;
                if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
                    updateProjectAnalysisStatus(
                        organizationId, projectId, AnalysisStatus.FAILED,
                        "Lost contact with the analysis service"
                    );
                    analysisProgressStore.remove(progressKey);
                    return;
                }
                continue;
            }
            consecutiveErrors = 0;
            analysisProgressStore.update(progressKey, status.getStage(), status.getMessage());

            if ("completed".equalsIgnoreCase(status.getStatus())) {
                ProjectModel project = updateProjectAnalysisStatus(
                    organizationId, projectId, AnalysisStatus.COMPLETED, null
                );
                project.setAnalysisCompletedAt(LocalDateTime.now());
                projectRepository.save(project);
                analysisProgressStore.remove(progressKey);
                log.info("Analysis completed successfully for project {}: {}", projectId, status.getBlueprintPath());
                persistLiveSnapshot(organizationId, projectId);
                return;
            }

            if ("failed".equalsIgnoreCase(status.getStatus())) {
                String errorMsg = status.getErrorMessage() != null
                    ? status.getErrorMessage()
                    : "Unknown analysis error";
                updateProjectAnalysisStatus(organizationId, projectId, AnalysisStatus.FAILED, errorMsg);
                analysisProgressStore.remove(progressKey);
                log.error("Analysis failed for project {}: {}", projectId, errorMsg);
                return;
            }
            // "queued" / "running" — keep polling
        }

        updateProjectAnalysisStatus(organizationId, projectId, AnalysisStatus.FAILED, "Analysis timed out");
        analysisProgressStore.remove(progressKey);
        log.error("Analysis timed out for project {}", projectId);
    }

    /**
     * Persists a {@code GraphSnapshot} row for the just-completed live analysis, mirroring
     * what {@code HistoricalAnalysisService} does for historical commits. This gives the
     * live/default blueprint a snapshotId that cluster overrides and future diffing can key
     * off — without it, only Phase-2 historical re-analyses had a snapshot to reference.
     * Best-effort: a failure here must not turn an otherwise-successful analysis into a
     * failed one, so it's logged and swallowed rather than propagated.
     */
    private void persistLiveSnapshot(UUID organizationId, UUID projectId) {
        try {
            Path blueprintPath = Paths.get(analysisOutputDir)
                    .resolve(organizationId.toString())
                    .resolve(projectId.toString())
                    .resolve("graph_blueprint.json");
            if (!Files.exists(blueprintPath)) {
                log.warn("[ANALYSIS] No blueprint file at {} — skipping snapshot persistence", blueprintPath);
                return;
            }
            snapshotPersistenceService.persistSnapshot(projectId, blueprintPath);
        } catch (Exception e) {
            log.warn("[ANALYSIS] Failed to persist graph snapshot for project {}: {}", projectId, e.getMessage());
        }
    }

    private AnalysisStatusResponseDto fetchAnalysisStatus(UUID projectId) {
        try {
            String url = pythonAnalyzerBaseUrl + "/analyze/" + projectId + "/status";
            ResponseEntity<AnalysisStatusResponseDto> response =
                restTemplate.getForEntity(url, AnalysisStatusResponseDto.class);
            return response.getBody();
        } catch (Exception e) {
            log.warn("Failed to poll analysis status for project {}: {}", projectId, e.getMessage());
            return null;
        }
    }

    // ---------------------------------------------------------------------------
    // Private helper methods
    // ---------------------------------------------------------------------------

    private AnalysisResponseDto callPythonAnalyzer(AnalysisRequestDto request) {
        return callPythonAnalyzer("/analyze", request);
    }

    private AnalysisResponseDto callPythonAnalyzer(String endpoint, AnalysisRequestDto request) {
        String url = pythonAnalyzerBaseUrl + endpoint;
        
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        
        HttpEntity<AnalysisRequestDto> httpEntity = new HttpEntity<>(request, headers);
        
        try {
            log.debug("Calling Python analyzer: {} with request: {}", url, request);
            
            ResponseEntity<AnalysisResponseDto> response = restTemplate.postForEntity(
                url,
                httpEntity,
                AnalysisResponseDto.class
            );
            
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                return response.getBody();
            } else {
                throw new RuntimeException("Invalid response from Python analyzer: " + response.getStatusCode());
            }
            
        } catch (ResourceAccessException e) {
            throw new RuntimeException("Python analyzer service is not available at " + pythonAnalyzerBaseUrl, e);
        } catch (Exception e) {
            throw new RuntimeException("Failed to call Python analyzer: " + e.getMessage(), e);
        }
    }

    private ProjectModel updateProjectAnalysisStatus(
            UUID organizationId,
            UUID projectId,
            AnalysisStatus status,
            String errorMessage
    ) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));
        
        project.setAnalysisStatus(status);
        if (errorMessage != null) {
            project.setUploadErrorMessage(errorMessage); // Reuse this field or add analysisErrorMessage
        }
        
        return projectRepository.save(project);
    }
}