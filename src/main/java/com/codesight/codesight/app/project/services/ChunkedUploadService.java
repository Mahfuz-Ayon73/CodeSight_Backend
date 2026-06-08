package com.codesight.codesight.app.project.services;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.*;
import java.nio.file.*;
import java.util.concurrent.ConcurrentHashMap;

@Slf4j
@Service
public class ChunkedUploadService {

    @Value("${codesight.storage.root:./storage/codebases}")
    private String storageRoot;

    // Track received chunks per uploadId
    private final ConcurrentHashMap<String, int[]> chunkTracker = new ConcurrentHashMap<>();

    /**
     * Save a chunk to a temp directory.
     * Returns the assembled file path when all chunks are received, null otherwise.
     */
    public Path saveChunk(
            String uploadId,
            int chunkIndex,
            int totalChunks,
            String fileName,
            MultipartFile chunk
    ) throws IOException {
        Path tempDir = Paths.get(storageRoot, "temp", uploadId);
        Files.createDirectories(tempDir);

        // Save this chunk
        Path chunkFile = tempDir.resolve("chunk_" + chunkIndex);
        Files.copy(chunk.getInputStream(), chunkFile, StandardCopyOption.REPLACE_EXISTING);
        log.info("[CHUNK] Saved chunk {}/{} for uploadId={}", chunkIndex + 1, totalChunks, uploadId);

        // Track received chunks
        chunkTracker.compute(uploadId, (id, counts) -> {
            if (counts == null) counts = new int[]{0};
            counts[0]++;
            return counts;
        });

        int received = chunkTracker.get(uploadId)[0];

        if (received == totalChunks) {
            // All chunks received — assemble the file
            log.info("[CHUNK] All {} chunks received for {}. Assembling...", totalChunks, uploadId);
            Path assembledFile = tempDir.resolve(fileName);
            assembleChunks(tempDir, assembledFile, totalChunks);
            chunkTracker.remove(uploadId);
            log.info("[CHUNK] Assembly complete: {}", assembledFile);
            return assembledFile;
        }

        return null; // Not done yet
    }

    private void assembleChunks(Path tempDir, Path outputFile, int totalChunks) throws IOException {
        try (OutputStream out = new BufferedOutputStream(new FileOutputStream(outputFile.toFile()))) {
            for (int i = 0; i < totalChunks; i++) {
                Path chunkFile = tempDir.resolve("chunk_" + i);
                Files.copy(chunkFile, out);
                Files.delete(chunkFile);
            }
        }
    }

    public void cleanupTempDir(String uploadId) {
        try {
            Path tempDir = Paths.get(storageRoot, "temp", uploadId);
            if (Files.exists(tempDir)) {
                try (var stream = Files.walk(tempDir)) {
                    stream.sorted(java.util.Comparator.reverseOrder())
                          .map(Path::toFile)
                          .forEach(File::delete);
                }
            }
        } catch (IOException e) {
            log.warn("[CHUNK] Failed to cleanup temp dir for uploadId={}: {}", uploadId, e.getMessage());
        }
    }
}
