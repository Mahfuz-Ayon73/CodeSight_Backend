package com.codesight.codesight.common.utils;

import org.springframework.web.multipart.MultipartFile;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * MultipartFile adapter for an already-assembled file on disk.
 * Used for chunked ZIP uploads.
 */
public class FileMultipartFile implements MultipartFile {

    private final Path file;
    private final String originalFilename;
    private final String contentType;

    public FileMultipartFile(Path file, String originalFilename, String contentType) {
        this.file = file;
        this.originalFilename = originalFilename;
        this.contentType = contentType;
    }

    @Override public String getName() { return "file"; }
    @Override public String getOriginalFilename() { return originalFilename; }
    @Override public String getContentType() { return contentType; }
    @Override public boolean isEmpty() { return file.toFile().length() == 0; }
    @Override public long getSize() { return file.toFile().length(); }

    @Override
    public byte[] getBytes() throws IOException {
        return Files.readAllBytes(file);
    }

    @Override
    public InputStream getInputStream() throws IOException {
        return new BufferedInputStream(new FileInputStream(file.toFile()));
    }

    @Override
    public void transferTo(File dest) throws IOException {
        Files.copy(file, dest.toPath());
    }
}
