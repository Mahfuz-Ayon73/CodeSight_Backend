package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.util.List;

/**
 * Per-file git-blame ownership breakdown as of HEAD. {@code path} matches
 * {@code BlueprintNode.canonical_path} so the frontend can join it directly
 * onto the graph without a second lookup.
 */
@Data
@Builder
public class FileOwnershipDto {
    private String path;
    /** Sorted descending by lines. */
    private List<AuthorShareDto> authors;
    private String primaryOwner;
    private String primaryOwnerEmail;
    private double primaryOwnerPercentage;
    private int totalLines;
}
