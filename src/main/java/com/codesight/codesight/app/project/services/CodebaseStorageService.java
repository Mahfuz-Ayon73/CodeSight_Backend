package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.config.StorageProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.UUID;
import java.util.stream.Stream;

@Service
@RequiredArgsConstructor
public class CodebaseStorageService {

    private final StorageProperties storageProperties;

    public Path resolveProjectRepoPath(UUID organizationId, UUID projectId) {
        return Path.of(storageProperties.root(), organizationId.toString(), projectId.toString(), "repo")
                .toAbsolutePath()
                .normalize();
    }

    public void prepareRepoDirectory(Path repoPath) throws IOException {
        if (Files.exists(repoPath)) {
            try (Stream<Path> paths = Files.walk(repoPath)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try {
                        Files.setAttribute(path, "dos:readonly", false);
                    } catch (UnsupportedOperationException | IOException ignored) {
                        // not a DOS-attribute filesystem, or attribute already gone
                    }
                    try {
                        Files.deleteIfExists(path);
                    } catch (IOException e) {
                        throw new RuntimeException("Failed to clear repository directory at " + path + ": " + e.getMessage(), e);
                    }
                });
            }
        }
        Files.createDirectories(repoPath);
    }
}
