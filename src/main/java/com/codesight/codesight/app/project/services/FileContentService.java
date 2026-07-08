package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.project.dto.FileContentDto;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.SeekableByteChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.regex.Pattern;

@Slf4j
@Service
@RequiredArgsConstructor
public class FileContentService {

    private final ProjectUploadService projectUploadService;

    private static final long MAX_FILE_BYTES = 2L * 1024 * 1024; // 2 MB cap
    private static final int BINARY_SNIFF_BYTES = 8192;
    private static final Pattern DRIVE_LETTER_PATTERN = Pattern.compile("^[A-Za-z]:");

    /**
     * Reads a file's raw text content for preview, resolved as
     * {@code storagePath/canonicalPath}. Path-traversal defenses are layered:
     * an up-front rejection of absolute/rooted paths (covers the case where
     * {@link Path#isAbsolute()} doesn't recognize a POSIX-style leading slash
     * on Windows), followed by the authoritative check that the normalized,
     * resolved path still lives under the normalized storage root.
     */
    public FileContentDto getFileContent(UUID organizationId, UUID projectId, UUID userId, String rawPath) {
        String storagePathStr = projectUploadService.getStoragePath(organizationId, projectId, userId);
        if (storagePathStr == null || storagePathStr.isBlank()) {
            throw new ResourceNotFoundException("Project has no stored source");
        }
        if (rawPath == null || rawPath.isBlank()) {
            throw new BadRequestException("path query parameter is required");
        }
        if (rawPath.startsWith("/") || rawPath.startsWith("\\") || DRIVE_LETTER_PATTERN.matcher(rawPath).find()
                || Paths.get(rawPath).isAbsolute()) {
            throw new BadRequestException("path must be a repo-relative path");
        }

        Path storageRoot = Paths.get(storagePathStr).normalize().toAbsolutePath();
        Path resolved = storageRoot.resolve(rawPath).normalize().toAbsolutePath();
        if (!resolved.startsWith(storageRoot)) {
            throw new BadRequestException("path escapes project root");
        }

        if (!Files.exists(resolved) || !Files.isRegularFile(resolved)) {
            throw new ResourceNotFoundException("File not found — it may have been purged, moved, or deleted");
        }

        long size;
        try {
            size = Files.size(resolved);
        } catch (IOException e) {
            throw new RuntimeException("Failed to stat file: " + e.getMessage(), e);
        }

        boolean truncated = size > MAX_FILE_BYTES;

        try {
            byte[] sniff = readUpTo(resolved, Math.min(BINARY_SNIFF_BYTES, size));
            boolean binary = containsNulByte(sniff);

            if (binary) {
                return FileContentDto.builder()
                        .canonicalPath(rawPath)
                        .content("")
                        .truncated(false)
                        .binary(true)
                        .sizeBytes(size)
                        .build();
            }

            byte[] bytes = truncated ? readUpTo(resolved, MAX_FILE_BYTES) : Files.readAllBytes(resolved);
            String content = new String(bytes, StandardCharsets.UTF_8);

            return FileContentDto.builder()
                    .canonicalPath(rawPath)
                    .content(content)
                    .truncated(truncated)
                    .binary(false)
                    .sizeBytes(size)
                    .build();
        } catch (IOException e) {
            throw new RuntimeException("Failed to read file: " + e.getMessage(), e);
        }
    }

    private static byte[] readUpTo(Path path, long limit) throws IOException {
        try (SeekableByteChannel channel = Files.newByteChannel(path, StandardOpenOption.READ)) {
            ByteBuffer buffer = ByteBuffer.allocate((int) limit);
            while (buffer.hasRemaining()) {
                if (channel.read(buffer) < 0) break;
            }
            buffer.flip();
            byte[] result = new byte[buffer.remaining()];
            buffer.get(result);
            return result;
        }
    }

    private static boolean containsNulByte(byte[] bytes) {
        for (byte b : bytes) {
            if (b == 0) return true;
        }
        return false;
    }
}
