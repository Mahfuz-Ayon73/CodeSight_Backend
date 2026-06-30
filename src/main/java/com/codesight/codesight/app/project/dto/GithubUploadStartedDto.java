package com.codesight.codesight.app.project.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.UUID;

/**
 * Returned with HTTP 202 by {@code POST /upload/github} to signal that the clone
 * has been queued. The actual result is delivered via the polling endpoint
 * {@code GET /upload/clone-status}.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GithubUploadStartedDto {
    private UUID projectId;
    private String status;   // always "cloning" for the initial response
    private String message;  // human-readable hint for the client
}
