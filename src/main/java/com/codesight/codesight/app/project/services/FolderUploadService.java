package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.exception.BadRequestException;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.List;

@Service
public class FolderUploadService {

    public void saveFolderFiles(List<MultipartFile> files, Path destination) throws IOException {
        if (files == null || files.isEmpty()) {
            throw new BadRequestException("At least one file is required for folder upload");
        }

        Path root = destination.toAbsolutePath().normalize();
        Files.createDirectories(root);

        int saved = 0;
        for (MultipartFile file : files) {
            if (file == null || file.isEmpty()) {
                continue;
            }

            String relativePath = resolveRelativePath(file);
            Path target = root.resolve(relativePath).normalize();

            if (!target.startsWith(root)) {
                throw new BadRequestException("Invalid file path in folder upload: " + relativePath);
            }

            if (relativePath.endsWith("/") || relativePath.endsWith("\\")) {
                Files.createDirectories(target);
                continue;
            }

            Files.createDirectories(target.getParent());
            Files.copy(file.getInputStream(), target, StandardCopyOption.REPLACE_EXISTING);
            saved++;
        }

        if (saved == 0) {
            throw new BadRequestException("No files were uploaded. Select a folder that contains source files.");
        }
    }

    private String resolveRelativePath(MultipartFile file) {
        String path = file.getOriginalFilename();
        if (path == null || path.isBlank()) {
            throw new BadRequestException("Each uploaded file must include a relative path (use a folder picker in the browser)");
        }

        path = path.replace('\\', '/').trim();

        while (path.startsWith("/")) {
            path = path.substring(1);
        }

        if (path.contains("..")) {
            throw new BadRequestException("Invalid path segment in upload: " + path);
        }

        return path;
    }
}
