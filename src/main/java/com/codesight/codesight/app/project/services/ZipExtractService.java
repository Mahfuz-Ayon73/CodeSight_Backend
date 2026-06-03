package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.exception.BadRequestException;
import org.apache.commons.compress.archivers.zip.ZipArchiveEntry;
import org.apache.commons.compress.archivers.zip.ZipArchiveInputStream;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Set;

@Service
public class ZipExtractService {

    // Directories that are never useful for analysis — skip them entirely
    private static final Set<String> BLACKLISTED_DIRS = Set.of(
        "node_modules", ".git", ".next", "dist", "build", ".turbo",
        "coverage", ".cache", "out", ".svn", "__pycache__", ".idea",
        ".vscode", "vendor", "target", "bin", "obj"
    );

    public void extractZip(MultipartFile file, Path destination) throws IOException {
        Path root = destination.toAbsolutePath().normalize();

        if (file == null || file.isEmpty()) {
            throw new BadRequestException("Zip file is required");
        }

        String filename = file.getOriginalFilename();
        if (filename == null || !filename.toLowerCase().endsWith(".zip")) {
            throw new BadRequestException("Only .zip archives are supported");
        }

        try (InputStream raw = file.getInputStream();
             BufferedInputStream buffered = new BufferedInputStream(raw);
             ZipArchiveInputStream zipInput = new ZipArchiveInputStream(buffered)) {

            ZipArchiveEntry entry;
            while ((entry = zipInput.getNextEntry()) != null) {
                String entryName = entry.getName().replace('\\', '/');

                // Skip any entry whose path contains a blacklisted directory segment
                if (isBlacklisted(entryName)) continue;

                if (entry.isDirectory()) {
                    Files.createDirectories(root.resolve(entryName).normalize());
                    continue;
                }

                Path target = root.resolve(entryName).normalize();
                if (!target.startsWith(root)) {
                    throw new BadRequestException("Zip archive contains invalid paths");
                }

                Files.createDirectories(target.getParent());
                Files.copy(zipInput, target, StandardCopyOption.REPLACE_EXISTING);
            }
        }
    }

    static boolean isBlacklisted(String entryPath) {
        String[] segments = entryPath.split("/");
        for (String segment : segments) {
            if (BLACKLISTED_DIRS.contains(segment)) return true;
        }
        return false;
    }
}
