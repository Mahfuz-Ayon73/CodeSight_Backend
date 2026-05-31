package com.codesight.codesight.app.organization.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OrganizationRequestDto {

    @NotBlank
    @Size(max = 120)
    private String name;

    @Size(max = 500)
    private String description;
}
