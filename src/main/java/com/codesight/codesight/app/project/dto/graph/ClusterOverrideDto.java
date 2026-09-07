package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

/**
 * Read-side shape for GET .../graph/overrides — one row per cluster that has an active
 * manual rename/re-summary within a snapshot. Distinct from {@link OverrideResponse},
 * which only acknowledges a single write.
 */
@Data
@Builder
public class ClusterOverrideDto {
    private String clusterId;
    private String overrideTitle;
    private String overrideSummary;
    private Long version;
}
