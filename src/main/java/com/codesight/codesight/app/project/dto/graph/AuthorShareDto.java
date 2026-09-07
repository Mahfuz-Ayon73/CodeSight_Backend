package com.codesight.codesight.app.project.dto.graph;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class AuthorShareDto {
    private String name;
    private String email;
    private int lines;
    /** Share of the file's blamed lines, 0-100, rounded to 1 decimal place. */
    private double percentage;
}
