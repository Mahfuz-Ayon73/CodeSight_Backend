package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class OwnershipResponse {
    private List<FileOwnershipDto> files;
    /** True when {@code paths} exceeded the per-request cap and was truncated. */
    private boolean truncated;
}
