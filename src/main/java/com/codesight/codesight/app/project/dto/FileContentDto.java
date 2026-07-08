package com.codesight.codesight.app.project.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Raw source content for a single file, resolved from the project's storage path
 * by canonical (repo-relative) path. Returned by {@code GET /{projectId}/file-content}.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FileContentDto {
    private String canonicalPath;
    private String content;
    private boolean truncated;
    private boolean binary;
    private long sizeBytes;
}
