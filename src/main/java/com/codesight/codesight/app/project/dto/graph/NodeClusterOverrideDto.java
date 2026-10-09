package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

/** Effective manual placement for one file within a graph snapshot. */
@Data
@Builder
public class NodeClusterOverrideDto {
    private String filePath;
    private String originalClusterId;
    private String overrideClusterId;
    private Long version;
}
