package com.codesight.codesight.app.project.dto.graph;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

/**
 * Body for POST /api/.../graph/ownership. The frontend passes the exact
 * {@code canonical_path}s it wants blamed (its blueprint's node paths) rather
 * than the backend re-deriving "which files count as source" — avoids
 * duplicating the analyzer's own file-selection rules on the Java side.
 */
@Data
public class OwnershipRequest {

    @NotEmpty
    @Size(max = 2000)
    private List<@Size(max = 4096) String> paths;
}
