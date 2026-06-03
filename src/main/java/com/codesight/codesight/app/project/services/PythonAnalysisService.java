package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.project.dto.AnalysisRequestDto;
import com.codesight.codesight.app.project.dto.AnalysisResponseDto;
import com.codesight.codesight.app.project.model.AnalysisStatus;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.ResourceAccessException;

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

    @Value("${codesight.python-analyzer.base-url:http://localhost:8000}")
    private String pythonAnalyzerBaseUrl;

    @Value("${codesight.analysis.output-dir:/tmp/codesight-analysis}")
    private String analysisOutputDir;

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
            
            // Call Python FastAPI service
            AnalysisResponseDto response = callPythonAnalyzer(request);
            
            if (response.getSuccess() != null && response.getSuccess()) {
                // Analysis succeeded — update status and store blueprint path
                ProjectModel project = updateProjectAnalysisStatus(
                    organizationId, 
                    projectId, 
                    AnalysisStatus.COMPLETED, 
                    null
                );
                
                // Store the blueprint path in the project (you might want to add this field)
                project.setAnalysisCompletedAt(LocalDateTime.now());
                // project.setBlueprintPath(response.getBlueprintPath()); // Add this field if needed
                projectRepository.save(project);
                
                log.info("Analysis completed successfully for project {}: {}", projectId, response.getBlueprintPath());
            } else {
                // Analysis failed
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
     * Get analysis status for a project from the Python service.
     */
    public String getAnalysisStatus(UUID projectId) {
        try {
            String url = pythonAnalyzerBaseUrl + "/analyze/" + projectId + "/status";
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            return response.getBody();
        } catch (Exception e) {
            log.warn("Failed to get analysis status for project {}: {}", projectId, e.getMessage());
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