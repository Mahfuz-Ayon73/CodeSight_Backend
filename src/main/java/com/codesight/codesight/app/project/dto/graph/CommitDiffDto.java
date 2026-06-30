package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
public class CommitDiffDto {
    private String sha;
    private String shortSha;
    private String message;
    private String author;
    private LocalDateTime timestamp;
    private List<String> addedFiles;
    private List<String> modifiedFiles;
    private List<String> deletedFiles;
    private int totalChanges;
}
