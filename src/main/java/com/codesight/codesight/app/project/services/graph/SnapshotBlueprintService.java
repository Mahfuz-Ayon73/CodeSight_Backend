package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.BlueprintDto;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;
import java.util.zip.GZIPInputStream;

/**
 * Reconstructs the full blueprint JSON for a historical {@link GraphSnapshot}, mirroring
 * how {@code ProjectAnalysisBlueprintService} reads the live blueprint off disk. Historical
 * blueprints are written per-commit by {@code HistoricalAnalysisService} under
 * {@code {analysisOutputDir}/{organizationId}/{projectId}/{commitSha}/graph_blueprint.json}.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SnapshotBlueprintService {

    private final GraphSnapshotRepository graphSnapshotRepository;
    private final ObjectMapper objectMapper;

    @Value("${codesight.analysis.output-dir:./storage/analysis}")
    private String analysisOutputDir;

    public BlueprintDto getSnapshotBlueprint(UUID organizationId, UUID projectId, UUID snapshotId) {
        GraphSnapshot snapshot = graphSnapshotRepository.findById(snapshotId)
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));

        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }

        if (snapshot.getCommitSha() != null) {
            Path blueprintPath = Paths.get(analysisOutputDir)
                    .resolve(organizationId.toString())
                    .resolve(projectId.toString())
                    .resolve(snapshot.getCommitSha())
                    .resolve("graph_blueprint.json");

            if (Files.exists(blueprintPath)) {
                try {
                    return objectMapper.readValue(blueprintPath.toFile(), BlueprintDto.class);
                } catch (IOException e) {
                    log.error("Failed to read snapshot blueprint at {}", blueprintPath, e);
                    throw new RuntimeException("Failed to read snapshot blueprint: " + e.getMessage());
                }
            }
            log.warn("[SNAPSHOT-BLUEPRINT] No file at {} — falling back to compressed_map", blueprintPath);
        }

        if (snapshot.getCompressedMap() != null) {
            try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(snapshot.getCompressedMap()))) {
                return objectMapper.readValue(gzip, BlueprintDto.class);
            } catch (IOException e) {
                log.error("Failed to read compressed blueprint for snapshot {}", snapshotId, e);
                throw new RuntimeException("Failed to read compressed snapshot blueprint: " + e.getMessage());
            }
        }

        throw new ResourceNotFoundException("Blueprint data not available for this snapshot");
    }
}
